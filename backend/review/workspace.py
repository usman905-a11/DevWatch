"""Path-safe, read-only local workspace filesystem access and manifest builder."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from backend.config import Config, SENSITIVE_DIR_NAMES, is_sensitive_rel_path
from .capture import EXCLUDED_DIRECTORIES, EXCLUDED_PATTERNS
from .stores import (
    CaptureCoverage,
    GitMetadata,
    SnapshotManifest,
    SourceEntry,
    _capture_hash,
    _content_hash,
    _git_hash,
)

DEFAULT_MAX_READ_BYTES = 2 * 1024 * 1024  # 2 MB
DEFAULT_SCAN_MAX_BYTES = 1024 * 1024  # 1 MB per source file for agent analysis

IGNORED_DIR_NAMES = frozenset({
    "node_modules",
    ".git",
    "dist",
    "build",
    "out",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    ".devwatch",
    "target",
    "vendor",
    *EXCLUDED_DIRECTORIES,
})


class WorkspaceError(ValueError):
    """Raised for invalid workspace roots or unsafe paths."""


class WorkspaceNotSetError(WorkspaceError):
    """Raised when an operation requires an active workspace root but none is set."""


class PathOutsideWorkspaceError(WorkspaceError):
    """Raised when a path escapes the active workspace root."""


class WorkspaceNotFoundError(FileNotFoundError):
    """Raised when a requested file or directory does not exist inside the workspace."""


@dataclass(frozen=True, slots=True)
class FsEntry:
    name: str
    path: str
    type: str  # "file" | "dir"
    size: int
    isSymlink: bool
    ignored: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "size": self.size,
            "isSymlink": self.isSymlink,
            "ignored": self.ignored,
        }


@dataclass(frozen=True, slots=True)
class FsReadResult:
    path: str
    size: int
    binary: bool
    tooLarge: bool
    maxBytes: int
    lineCount: int | None
    content: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "binary": self.binary,
            "tooLarge": self.tooLarge,
            "maxBytes": self.maxBytes,
            "lineCount": self.lineCount,
            "content": self.content,
        }


def _normalize_rel(rel_path: str) -> str:
    cleaned = rel_path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.strip("/")


def _load_gitignore_patterns(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    try:
        lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    patterns: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line)
    return patterns


def _matches_gitignore(rel_posix: str, name: str, is_dir: bool, patterns: Iterable[str]) -> bool:
    for raw_pattern in patterns:
        pattern = raw_pattern.rstrip("/")
        if raw_pattern.endswith("/") and not is_dir:
            # Directory-only rule still applies if any parent segment matches when walking,
            # or to the directory entry itself.
            if "/" not in pattern and fnmatch.fnmatch(name, pattern):
                return True
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
            continue
        anchored = pattern.startswith("/")
        if anchored:
            pattern = pattern.lstrip("/")
            if fnmatch.fnmatch(rel_posix, pattern) or (is_dir and rel_posix.startswith(pattern + "/")):
                return True
        elif "/" in pattern:
            if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(rel_posix, f"*/{pattern}"):
                return True
        else:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_posix, pattern):
                return True
    return False


def _is_link_or_reparse(path: Path, dirent: os.DirEntry[str] | None = None) -> bool:
    """Detect POSIX symlinks and Windows symlinks/junction reparse points without following."""
    try:
        if dirent is not None and dirent.is_symlink():
            return True
    except OSError:
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(attrs & reparse)


def _symlink_escapes_root(root_real: Path, path: Path) -> bool:
    try:
        resolved = Path(os.path.realpath(path))
        resolved.relative_to(root_real)
        return False
    except (OSError, ValueError):
        return True


def is_ignored_entry(rel_posix: str, name: str, is_dir: bool, gitignore_patterns: Iterable[str] = ()) -> bool:
    if name in IGNORED_DIR_NAMES or name.lower() in SENSITIVE_DIR_NAMES:
        return True
    if is_sensitive_rel_path(rel_posix):
        return True
    if not is_dir:
        lower_name = name.lower()
        if lower_name in Config.BLOCKED_FILENAMES or lower_name.startswith(".env."):
            return True
        for pat in (*EXCLUDED_PATTERNS, *Config.BLOCKED_PATTERNS):
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(lower_name, pat):
                return True
    parts = [part for part in rel_posix.split("/") if part]
    if any(part in IGNORED_DIR_NAMES or part.lower() in SENSITIVE_DIR_NAMES for part in parts):
        return True
    return _matches_gitignore(rel_posix, name, is_dir, gitignore_patterns)


def is_binary_bytes(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def _resolve_within_root(root_real: Path, rel_path: str = "", *, allow_root: bool = False) -> tuple[Path, str]:
    if "\x00" in rel_path:
        raise PathOutsideWorkspaceError("invalid null byte in path")
    normalized = _normalize_rel(rel_path)
    if not normalized:
        if allow_root:
            return root_real, ""
        raise PathOutsideWorkspaceError("relative path must not be empty")
    if os.path.isabs(rel_path) or (len(rel_path) >= 2 and rel_path[1] == ":"):
        raise PathOutsideWorkspaceError("absolute paths are not allowed")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PathOutsideWorkspaceError("path traversal segments are not allowed")

    candidate = Path(os.path.realpath(root_real.joinpath(*parts)))
    try:
        relative = candidate.relative_to(root_real)
    except ValueError as exc:
        raise PathOutsideWorkspaceError(f"path escapes workspace root: {rel_path}") from exc
    rel_posix = relative.as_posix()
    if rel_posix == ".":
        rel_posix = ""
    return candidate, rel_posix


@dataclass
class WorkspaceManager:
    """Manages the single active read-only local workspace root."""

    root: Path | None = None
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES
    _gitignore_cache: list[str] = field(default_factory=list, init=False, repr=False)

    def set_root(self, path: str | Path) -> Path:
        raw = str(path).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            raw = raw[1:-1].strip()
        if not raw:
            raise WorkspaceError("workspace path must not be empty")
        resolved = Path(os.path.realpath(raw))
        if not resolved.exists() or not resolved.is_dir():
            raise WorkspaceError(f"workspace path is not an existing directory: {path}")
        self.root = resolved
        self._gitignore_cache = _load_gitignore_patterns(resolved)
        return resolved

    def get_root(self) -> Path:
        if self.root is None:
            raise WorkspaceNotSetError("no active workspace is open")
        return self.root

    def resolve_safe(self, rel_path: str = "", *, allow_root: bool = False) -> tuple[Path, str]:
        root_real = self.get_root()
        return _resolve_within_root(root_real, rel_path, allow_root=allow_root)

    def list_dir(self, rel_path: str = "") -> list[FsEntry]:
        root_real = self.get_root()
        target, rel_prefix = _resolve_within_root(root_real, rel_path, allow_root=True)
        if not target.exists():
            raise WorkspaceNotFoundError(f"directory not found: {rel_path or '.'}")
        if not target.is_dir():
            raise WorkspaceError(f"path is not a directory: {rel_path}")

        patterns = _load_gitignore_patterns(root_real)
        entries: list[FsEntry] = []
        try:
            with os.scandir(target) as it:
                for dirent in it:
                    name = dirent.name
                    child_rel = f"{rel_prefix}/{name}" if rel_prefix else name
                    dirent_path = Path(dirent.path)
                    is_symlink = _is_link_or_reparse(dirent_path, dirent)
                    if is_symlink and _symlink_escapes_root(root_real, dirent_path):
                        # Never stat or reveal target type/size for links escaping workspace root.
                        entries.append(
                            FsEntry(
                                name=name,
                                path=child_rel,
                                type="file",
                                size=0,
                                isSymlink=True,
                                ignored=True,
                            )
                        )
                        continue
                    try:
                        is_dir = dirent.is_dir(follow_symlinks=is_symlink)
                    except OSError:
                        is_dir = False
                    size = 0
                    if not is_dir:
                        try:
                            size = dirent.stat(follow_symlinks=is_symlink).st_size
                        except OSError:
                            size = 0
                    ignored = is_ignored_entry(child_rel, name, is_dir, patterns)
                    if is_symlink and not ignored:
                        try:
                            target_rel = Path(os.path.realpath(dirent_path)).relative_to(root_real).as_posix()
                            if is_sensitive_rel_path(target_rel):
                                ignored = True
                        except (OSError, ValueError):
                            ignored = True
                    entries.append(
                        FsEntry(
                            name=name,
                            path=child_rel,
                            type="dir" if is_dir else "file",
                            size=size,
                            isSymlink=is_symlink,
                            ignored=ignored,
                        )
                    )
        except OSError as exc:
            raise WorkspaceError(f"unable to list directory {rel_path or '.'}: {exc}") from exc

        entries.sort(key=lambda item: (0 if item.type == "dir" else 1, item.name.lower(), item.name))
        return entries

    def read_file(self, rel_path: str, *, max_bytes: int | None = None) -> FsReadResult:
        cap = self.max_read_bytes if max_bytes is None else max_bytes
        raw_norm = _normalize_rel(rel_path)
        if raw_norm and is_sensitive_rel_path(raw_norm):
            raise PathOutsideWorkspaceError(f"access to sensitive file is forbidden: {raw_norm}")
        target, norm_rel = self.resolve_safe(rel_path, allow_root=False)
        if is_sensitive_rel_path(norm_rel):
            raise PathOutsideWorkspaceError(f"access to sensitive file is forbidden: {norm_rel}")
        if not target.exists():
            raise WorkspaceNotFoundError(f"file not found: {rel_path}")
        if not target.is_file():
            raise WorkspaceError(f"path is not a file: {rel_path}")

        size = target.stat().st_size
        if size > cap:
            return FsReadResult(
                path=norm_rel,
                size=size,
                binary=False,
                tooLarge=True,
                maxBytes=cap,
                lineCount=None,
                content=None,
            )

        raw = target.read_bytes()
        if is_binary_bytes(raw):
            return FsReadResult(
                path=norm_rel,
                size=size,
                binary=True,
                tooLarge=False,
                maxBytes=cap,
                lineCount=None,
                content=None,
            )

        text = raw.decode("utf-8")
        return FsReadResult(
            path=norm_rel,
            size=size,
            binary=False,
            tooLarge=False,
            maxBytes=cap,
            lineCount=len(text.splitlines()),
            content=text,
        )


def build_workspace_manifest(
    root: str | Path,
    *,
    max_file_bytes: int = DEFAULT_SCAN_MAX_BYTES,
    max_total_bytes: int = Config.MAX_REPO_TOTAL_BYTES,
) -> SnapshotManifest:
    """Build a lightweight manifest of analyzable files directly from a live workspace."""
    root_real = Path(os.path.realpath(str(root)))
    if not root_real.exists() or not root_real.is_dir():
        raise WorkspaceError(f"workspace path is not an existing directory: {root}")

    patterns = _load_gitignore_patterns(root_real)
    entries: dict[str, SourceEntry] = {}
    skipped_reasons: dict[str, str] = {}
    excluded_counts: dict[str, int] = {}
    discovered_count = 0
    total_bytes = 0

    def _record_skip(rel: str, reason: str, *, store_path: bool = True) -> None:
        excluded_counts[reason] = excluded_counts.get(reason, 0) + 1
        if store_path:
            skipped_reasons[rel] = reason

    for dirpath, dirnames, filenames in os.walk(root_real, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root_real).as_posix()
        if rel_dir == ".":
            rel_dir = ""

        kept_dirs: list[str] = []
        for dname in sorted(dirnames):
            d_rel = f"{rel_dir}/{dname}" if rel_dir else dname
            d_full = Path(dirpath) / dname
            if _is_link_or_reparse(d_full):
                discovered_count += 1
                _record_skip(d_rel, "symlink_directory")
                continue
            if is_ignored_entry(d_rel, dname, True, patterns):
                if dname not in {".git", ".devwatch"}:
                    discovered_count += 1
                    _record_skip(d_rel, "ignored", store_path=False)
                continue
            kept_dirs.append(dname)
        dirnames[:] = kept_dirs

        for fname in sorted(filenames):
            discovered_count += 1
            f_rel = f"{rel_dir}/{fname}" if rel_dir else fname
            f_full = Path(dirpath) / fname
            if _is_link_or_reparse(f_full) and _symlink_escapes_root(root_real, f_full):
                _record_skip(f_rel, "outside_workspace")
                continue
            if is_sensitive_rel_path(f_rel):
                _record_skip(f_rel, "excluded_secret")
                continue
            if is_ignored_entry(f_rel, fname, False, patterns):
                _record_skip(f_rel, "ignored", store_path=False)
                continue
            try:
                resolved, norm_rel = _resolve_within_root(root_real, f_rel, allow_root=False)
            except PathOutsideWorkspaceError:
                _record_skip(f_rel, "outside_workspace")
                continue
            if is_sensitive_rel_path(norm_rel):
                _record_skip(f_rel, "excluded_secret")
                continue

            if not resolved.is_file():
                continue
            try:
                size = resolved.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes:
                _record_skip(norm_rel, "too_large")
                continue
            if total_bytes + size > max_total_bytes:
                _record_skip(norm_rel, "total_size_limit")
                continue
            try:
                raw = resolved.read_bytes()
            except OSError:
                _record_skip(norm_rel, "unreadable")
                continue
            if is_binary_bytes(raw):
                _record_skip(norm_rel, "binary")
                continue

            text = raw.decode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            total_bytes += len(raw)
            entries[norm_rel] = SourceEntry(
                content_hash=digest,
                byte_count=len(raw),
                line_count=len(text.splitlines()),
            )

    limitations: list[str] = []
    if len(entries) > Config.MAX_FILES_PER_REVIEW:
        limitations.append(
            f"Workspace contains {len(entries)} eligible files (exceeding single-batch prompt capacity "
            f"{Config.MAX_FILES_PER_REVIEW}); planner prioritization and partial omission accounting active."
        )

    content_digest = _content_hash(entries)
    coverage = CaptureCoverage(
        skipped=skipped_reasons,
        failed={},
        limitations=limitations,
        discovered_count=discovered_count,
        excluded_by_reason=excluded_counts,
    )
    git_meta = GitMetadata()
    manifest_id = hashlib.sha256(content_digest.encode("utf-8")).hexdigest()[:32]

    return SnapshotManifest(
        snapshot_id=manifest_id,
        owner="local",
        content_hash=content_digest,
        entries=entries,
        capture_coverage=coverage,
        capture_hash=_capture_hash(coverage),
        git_metadata=git_meta,
        git_hash=_git_hash(git_meta),
    )
