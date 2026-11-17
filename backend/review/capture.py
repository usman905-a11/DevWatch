"""Local client capture and read-only Git scope selection, with explicit omissions.

Only operator-selected files are read. No repository command, hook, external diff,
model or reviewed-source write is part of this collector.
"""
import fnmatch
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Literal

from pydantic import Field

from devwatch.config import Config
from devwatch.review.contracts import ContractModel, SourceLocation
from devwatch.review.stores import CaptureCoverage, GitMetadata, validate_source_path


EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h",
              ".html", ".css", ".md", ".json", ".yaml", ".yml", ".toml"}
EXCLUDED_DIRECTORIES = {".git", ".devwatch", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "coverage"}
EXCLUDED_PATTERNS = ("*.min.js", "*.min.css", "*.map", "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml")
MAX_CATALOG_ENTRIES = 10_000
GIT_OUTPUT_BYTES = 250_000


class CapturedSource(ContractModel):
    root: Path
    files: dict[str, str]
    changed_files: list[str]
    scope_kind: Literal["file", "directory", "git_changes"]
    coverage: CaptureCoverage = Field(default_factory=CaptureCoverage)
    git_metadata: GitMetadata = Field(default_factory=GitMetadata)


def _git(root: Path, *arguments: str, timeout_seconds: float = 10) -> tuple[int, bytes]:
    began = time.monotonic()
    executable = shutil.which("git")
    if executable is None or Path(executable).resolve().is_relative_to(root):
        raise OSError("trusted Git executable unavailable")
    environment = {key: value for key, value in os.environ.items() if key.upper() in
                   {"PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP"}}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    repository = next((directory for directory in (root, *root.parents) if (directory / ".git").exists()), root)
    argv = [executable, "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false",
            "-c", "core.untrackedCache=false", "-c", f"safe.directory={repository}", "-C", str(root)]
    if arguments and arguments[0] in {"status", "diff", "log"}:
        code, keys = _git(root, "config", "--null", "--name-only", "--get-regexp", r"^filter\..*\.(clean|smudge|process)$", timeout_seconds=timeout_seconds)
        if code not in {0, 1}:
            raise ValueError("Git filter configuration unavailable")
        for driver in sorted({key.rsplit(".", 1)[0] for key in keys.decode("utf-8").split("\0") if key}):
            for setting in ("clean=", "smudge=", "process=", "required=false"):
                argv.extend(["-c", driver + "." + setting])
    argv.extend(arguments)
    # Disk-backed capture avoids allocating arbitrarily large Git output in RAM.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(argv, stdout=output, stderr=subprocess.DEVNULL, env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = began + timeout_seconds
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline or os.fstat(output.fileno()).st_size > GIT_OUTPUT_BYTES:
                    raise TimeoutError("Git metadata exceeds its time/output bound")
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            output.seek(0)
            data = output.read(GIT_OUTPUT_BYTES + 1)
            if len(data) > GIT_OUTPUT_BYTES:
                raise ValueError("Git metadata output bound exceeded")
            return process.returncode, data
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def _link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _excluded_directory(parts) -> bool:
    return any(part.lower() in EXCLUDED_DIRECTORIES or part.startswith(".") for part in parts)


def capture_source(target: str | Path) -> CapturedSource:
    requested = Path(target).absolute()
    if not requested.exists() or _link(requested) or not (requested.is_file() or requested.is_dir()):
        raise ValueError("target must be a regular source file or directory")
    single = requested.is_file()
    root = requested.parent.resolve() if single else requested.resolve()
    coverage = CaptureCoverage()
    files, changed, catalog = {}, set(), []
    scope_kind = "file" if single else "directory"
    def omission(name, reason, *, failed=False):
        try:
            name = SourceLocation.relative_source_path(name)
            if len(name.encode("utf-8")) > 1024:
                raise ValueError("unbounded path")
        except ValueError:
            if "Some filenames could not be represented safely." not in coverage.limitations:
                coverage.limitations.append("Some filenames could not be represented safely.")
            return
        bucket = coverage.failed if failed else coverage.skipped
        if len(bucket) < 1000:
            bucket[name] = reason
        elif "Capture omission listing is truncated at 1000 paths per category." not in coverage.limitations:
            coverage.limitations.append("Capture omission listing is truncated at 1000 paths per category.")
    if single:
        catalog, changed = [requested.name], {requested.name}
    else:
        try:
            code, _ = _git(root, "rev-parse", "--is-inside-work-tree")
            if code == 0:
                prefix_code, prefix_bytes = _git(root, "rev-parse", "--show-prefix")
                list_code, listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", ".")
                stage_code, staged = _git(root, "ls-files", "--stage", "-z", "--", ".")
                status_code, status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                                           "--ignore-submodules=all", "--", ".")
                if any(code != 0 for code in (prefix_code, list_code, stage_code, status_code)):
                    raise ValueError("Git scope unavailable")
                catalog = list(dict.fromkeys(name for name in listed.decode("utf-8").split("\0") if name))
                submodules = set()
                for record in staged.decode("utf-8").split("\0"):
                    if record:
                        metadata, name = record.split("\t", 1)
                        if metadata.split()[0] == "160000":
                            submodules.add(name)
                            omission(name, "git_submodule_not_captured")
                catalog = [name for name in catalog if name not in submodules]
                prefix = prefix_bytes.decode("utf-8").rstrip("\r\n")
                records, position = status.decode("utf-8").split("\0"), 0
                while position < len(records) and records[position]:
                    record = records[position]
                    if len(record) < 4 or record[2] != " ":
                        raise ValueError("invalid Git status record")
                    name = record[3:]
                    if not name.startswith(prefix):
                        raise ValueError("Git status escaped requested scope")
                    name = name[len(prefix):]
                    if "D" in record[:2]:
                        omission(name, "deleted_source_unavailable")
                    else:
                        changed.add(name)
                    position += 2 if any(kind in record[:2] for kind in "RC") else 1
                scope_kind = "git_changes"
                coverage.limitations.append("Git scope uses status paths; diff hunks and historical source are not captured.")
                coverage.limitations.append("External Git filters are disabled; filter-managed files may appear changed.")
                if submodules:
                    coverage.limitations.append("Git submodules are not traversed or captured; review each selected submodule separately.")
        except (OSError, ValueError, TimeoutError):
            catalog, changed = [], set()
            coverage.limitations.append("Git metadata unavailable; captured source is reviewed as full scope.")
        if scope_kind != "git_changes":
            entries, pending = 0, [root]
            deadline = time.monotonic() + 10
            while pending and entries < MAX_CATALOG_ENTRIES:
                if time.monotonic() >= deadline:
                    coverage.limitations.append("Directory catalog time limit reached.")
                    break
                directory = pending.pop()
                relative = directory.relative_to(root)
                try:
                    with os.scandir(directory) as listing:
                        while entries < MAX_CATALOG_ENTRIES:
                            if time.monotonic() >= deadline:
                                coverage.limitations.append("Directory catalog time limit reached.")
                                pending.clear()
                                break
                            entry = next(listing, None)
                            if entry is None:
                                break
                            entries += 1  # Charge excluded, inaccessible and directory entries too.
                            name = (relative / entry.name).as_posix()
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    if _excluded_directory((entry.name,)) or _link(Path(entry.path)):
                                        omission(name, "excluded_directory")
                                    elif len(relative.parts) >= Config.MAX_DIRECTORY_DEPTH:
                                        omission(name, "directory_depth_limit")
                                    else:
                                        pending.append(Path(entry.path))
                                else:
                                    catalog.append(name)
                            except OSError:
                                omission(name, "unavailable_source", failed=True)
                except OSError:
                    if directory == root:
                        coverage.limitations.append("Selected directory could not be enumerated.")
                    else:
                        omission(relative.as_posix(), "unavailable_directory", failed=True)
            if entries >= MAX_CATALOG_ENTRIES:
                coverage.limitations.append(f"Directory catalog entry limit reached ({MAX_CATALOG_ENTRIES}).")
    candidates = sorted(set(catalog) | changed, key=lambda name: (name not in changed, name))
    if len(candidates) > MAX_CATALOG_ENTRIES:
        candidates = candidates[:MAX_CATALOG_ENTRIES]
        coverage.limitations.append(f"File catalog entry limit reached ({MAX_CATALOG_ENTRIES}); remaining paths were not enumerated in coverage.")
    total_bytes = 0
    for raw in candidates:
        if _excluded_directory(Path(raw).parts[:-1]):
            omission(raw, "excluded_directory")
            continue
        try:
            name = validate_source_path(raw)
        except ValueError:
            omission(raw, "excluded_source")
            continue
        path = root / name
        if path.suffix.lower() not in EXTENSIONS or any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in EXCLUDED_PATTERNS):
            omission(name, "excluded_source")
            continue
        if len(files) >= Config.MAX_FILES_PER_REVIEW:
            omission(name, "snapshot_file_limit")
            continue
        try:
            # Refuse links/reparse ancestors and re-check containment after reading.
            if any(_link(parent) for parent in [path, *path.parents] if parent.is_relative_to(root)):
                omission(name, "linked_source")
                continue
            if not path.resolve().is_relative_to(root) or not path.is_file():
                omission(name, "unavailable_source", failed=True)
                continue
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                data = stream.read(Config.MAX_BYTES_PER_FILE + 1)
                after = os.fstat(stream.fileno())
            if len(data) > Config.MAX_BYTES_PER_FILE:
                omission(name, "snapshot_file_size_limit", failed=True)
                continue
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size) or not path.resolve().is_relative_to(root):
                omission(name, "source_changed_during_capture", failed=True)
                continue
            if total_bytes + len(data) > Config.MAX_REPO_TOTAL_BYTES:
                omission(name, "snapshot_total_size_limit", failed=True)
                continue
            try:
                if b"\0" in data:
                    raise UnicodeError()
                text = data.decode("utf-8")
            except UnicodeError:
                omission(name, "invalid_text_source", failed=True)
                continue
            files[name] = text
            total_bytes += len(data)
        except OSError:
            # Deleted files already have a precise omission; never erase it.
            if name not in coverage.skipped:
                omission(name, "unavailable_source", failed=True)
    selected = sorted(set(files) & changed) if scope_kind == "git_changes" else sorted(files)
    metadata = GitMetadata()
    if scope_kind == "git_changes":
        deadline = time.monotonic() + 5
        for name in selected:
            if time.monotonic() >= deadline or len(metadata.diffs) >= 20:
                metadata.limitations.append("Git metadata collection is limited to five seconds and twenty paths.")
                break
            try:
                diff = {}
                for category, flags in (("staged", ("--cached",)), ("unstaged", ())):
                    code, raw = _git(root, "diff", *flags, "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=3", "--", name,
                                     timeout_seconds=max(.001, deadline - time.monotonic()))
                    if code:
                        raise ValueError("Git diff unavailable")
                    diff[category] = raw[:8192].decode("utf-8", errors="ignore")
                    if len(raw) > 8192 and "Git diff text is truncated at 8192 bytes per category." not in metadata.limitations:
                        metadata.limitations.append("Git diff text is truncated at 8192 bytes per category.")
                metadata.diffs[name] = diff
                code, history = _git(root, "log", "-n", "5", "--format=%h %s", "--", name,
                                     timeout_seconds=max(.001, deadline - time.monotonic()))
                if code == 0:
                    metadata.history[name] = [line.encode()[:1024].decode("utf-8", errors="ignore") for line in history.decode("utf-8", errors="replace").splitlines()[:5]]
                if len(metadata.model_dump_json().encode()) > 150_000:
                    metadata.limitations.append("Git metadata byte limit reached; remaining paths omitted.")
                    break
            except (OSError, ValueError, TimeoutError):
                metadata.limitations.append("Some Git metadata was unavailable within capture limits.")
                break
    return CapturedSource(root=root, files=files, changed_files=selected, scope_kind=scope_kind, coverage=coverage,
                          git_metadata=GitMetadata.model_validate(metadata.model_dump()))
