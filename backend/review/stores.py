"""Separated local store locations and immutable source snapshots in SQLite."""

from dataclasses import dataclass
import fnmatch
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.config import Config, is_sensitive_rel_path
from backend.review.contracts import ContractModel, SourceLocation
from backend.review.jobs import _SQLiteStore


@dataclass(frozen=True)
class StoreLayout:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def app_db(self) -> Path:
        return self.root / "devwatch.sqlite"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints.sqlite"

    @property
    def repo_cache_db(self) -> Path:
        return self.root / "cache" / "repo-cache.sqlite"


class SnapshotIntegrityError(ValueError):
    pass


class SourceEntry(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content_hash: str
    byte_count: int = Field(ge=0)
    line_count: int = Field(ge=0)


class CaptureCoverage(ContractModel):
    """Client-reported omissions; this contract cannot assert source inspection."""
    skipped: dict[str, str] = Field(default_factory=dict, max_length=1000)
    failed: dict[str, str] = Field(default_factory=dict, max_length=1000)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    discovered_count: int | None = Field(default=None, ge=0)
    excluded_by_reason: dict[str, int] | None = None

    @field_validator("skipped", "failed")
    @classmethod
    def bounded_paths_and_reasons(cls, value):
        result = {}
        for name, reason in value.items():
            path = SourceLocation.relative_source_path(name)
            if len(path.encode("utf-8")) > 1024 or not re.fullmatch(r"[a-z][a-z_]{0,127}", reason):
                raise ValueError("capture omissions require bounded paths and reason codes")
            result[path] = reason
        return result

    @field_validator("limitations")
    @classmethod
    def bounded_explanations(cls, values):
        if any(not value or len(value.encode("utf-8")) > 512 for value in values):
            raise ValueError("capture explanations must be bounded")
        return values


class GitMetadata(ContractModel):
    diffs: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100)
    history: dict[str, list[str]] = Field(default_factory=dict, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def bounded_metadata(self):
        for path in set(self.diffs) | set(self.history):
            validate_source_path(path)
        if any(set(value) != {"staged", "unstaged"} or any(len(text.encode()) > 8192 for text in value.values()) for value in self.diffs.values()):
            raise ValueError("Git diffs require bounded staged and unstaged text")
        if any(len(values) > 5 or any(len(value.encode()) > 1024 for value in values) for values in self.history.values()):
            raise ValueError("Git history must be bounded")
        if len(self.model_dump_json().encode()) > 200_000 or any(len(value.encode()) > 512 for value in self.limitations):
            raise ValueError("Git metadata exceeds its byte bound")
        return self


class SnapshotManifest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_id: str
    owner: str
    content_hash: str
    entries: dict[str, SourceEntry]
    capture_coverage: CaptureCoverage = Field(default_factory=CaptureCoverage)
    capture_hash: str = Field(default_factory=lambda: _capture_hash(CaptureCoverage()))
    git_metadata: GitMetadata = Field(default_factory=GitMetadata)
    git_hash: str = Field(default_factory=lambda: _git_hash(GitMetadata()))


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _content_hash(entries: dict[str, SourceEntry]) -> str:
    contents = {path: entry.model_dump(mode="json") for path, entry in entries.items()}
    return sha256(_canonical_json(contents).encode("utf-8")).hexdigest()


def _capture_hash(coverage: CaptureCoverage) -> str:
    return sha256(_canonical_json(coverage.model_dump(mode="json")).encode("utf-8")).hexdigest()


def _git_hash(metadata: GitMetadata) -> str:
    return sha256(_canonical_json(metadata.model_dump(mode="json")).encode("utf-8")).hexdigest()


def validate_source_path(name: str) -> str:
    name = SourceLocation.relative_source_path(name)
    excluded = {".git", ".devwatch", ".venv", "node_modules", "__pycache__"}
    if is_sensitive_rel_path(name):
        raise ValueError("sensitive or generated source path is excluded")
    for part in Path(name).parts:
        if (part.lower().startswith(".env") or part.lower() in excluded
                or part.lower() in Config.BLOCKED_FILENAMES
                or any(fnmatch.fnmatch(part.lower(), pattern) for pattern in Config.BLOCKED_PATTERNS)):
            raise ValueError("sensitive or generated source path is excluded")
    return name


class ArtifactStore(_SQLiteStore):
    """SQLite-backed immutable snapshots and read-only evidence records."""

    def __init__(self, path: Path | str):
        super().__init__(
            path,
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY, owner TEXT NOT NULL, manifest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshot_files (
                snapshot_id TEXT NOT NULL, file_path TEXT NOT NULL, content TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, file_path)
            );
            CREATE TABLE IF NOT EXISTS evidence (
                snapshot_id TEXT NOT NULL, evidence_ref TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, evidence_ref)
            );
            """,
        )

    @staticmethod
    def _validate_snapshot_id(snapshot_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
            raise ValueError("invalid snapshot identity")

    def capture(self, *, owner: str, files: dict[str, str], capture_coverage: CaptureCoverage | None = None,
                git_metadata: GitMetadata | None = None) -> SnapshotManifest:
        if not owner or len(owner) > 256:
            raise ValueError("bounded snapshot owner is required")
        if len(files) > Config.MAX_FILES_PER_REVIEW:
            raise ValueError("snapshot file count exceeded")
        entries, encoded_texts, identities = {}, {}, set()
        for raw_path, content in files.items():
            path = validate_source_path(raw_path)
            identity = os.path.normcase(path)
            if identity in identities:
                raise ValueError("duplicate normalized source path")
            identities.add(identity)
            data = content.encode("utf-8")
            if len(data) > Config.MAX_BYTES_PER_FILE:
                raise ValueError("snapshot file size exceeded")
            encoded_texts[path] = content
            entries[path] = SourceEntry(content_hash=sha256(data).hexdigest(), byte_count=len(data),
                                        line_count=len(content.splitlines()))
        if sum(entry.byte_count for entry in entries.values()) > Config.MAX_REPO_TOTAL_BYTES:
            raise ValueError("snapshot total size exceeded")
        coverage = CaptureCoverage.model_validate((capture_coverage or CaptureCoverage()).model_dump())
        metadata = GitMetadata.model_validate((git_metadata or GitMetadata()).model_dump())
        if not (set(metadata.diffs) | set(metadata.history)).issubset(entries):
            raise ValueError("Git metadata must belong to captured source")
        manifest = SnapshotManifest(snapshot_id=uuid4().hex, owner=owner,
                                    content_hash=_content_hash(entries), entries=entries,
                                    capture_coverage=coverage, capture_hash=_capture_hash(coverage),
                                    git_metadata=metadata, git_hash=_git_hash(metadata))
        with self._transaction() as db:
            db.execute(
                "INSERT INTO snapshots(snapshot_id,owner,manifest) VALUES(?,?,?)",
                (manifest.snapshot_id, owner, manifest.model_dump_json()),
            )
            db.executemany(
                "INSERT INTO snapshot_files(snapshot_id,file_path,content) VALUES(?,?,?)",
                [(manifest.snapshot_id, path, content) for path, content in encoded_texts.items()],
            )
        return manifest

    def manifest(self, snapshot_id: str, *, owner: str) -> SnapshotManifest:
        self._validate_snapshot_id(snapshot_id)
        with self._transaction() as db:
            row = db.execute("SELECT manifest FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("snapshot not found")
        manifest = SnapshotManifest.model_validate_json(row["manifest"])
        if manifest.owner != owner:
            raise PermissionError("snapshot is not owned by this principal")
        if (manifest.snapshot_id != snapshot_id or _content_hash(manifest.entries) != manifest.content_hash
                or _capture_hash(manifest.capture_coverage) != manifest.capture_hash
                or _git_hash(manifest.git_metadata) != manifest.git_hash):
            raise SnapshotIntegrityError("snapshot manifest identity mismatch")
        return manifest

    def read_source(self, snapshot_id: str, file_path: str, *, owner: str) -> str:
        manifest = self.manifest(snapshot_id, owner=owner)
        file_path = validate_source_path(file_path)
        entry = manifest.entries.get(file_path)
        if entry is None:
            raise FileNotFoundError("source was not captured in this snapshot")
        with self._transaction() as db:
            row = db.execute(
                "SELECT content FROM snapshot_files WHERE snapshot_id=? AND file_path=?",
                (snapshot_id, file_path),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("source was not captured in this snapshot")
        text = row["content"]
        data = text.encode("utf-8")
        if len(data) != entry.byte_count or sha256(data).hexdigest() != entry.content_hash:
            raise SnapshotIntegrityError("snapshot source content changed")
        return text

    def put_evidence(self, snapshot_id: str, evidence_ref: str, payload: str) -> None:
        self._validate_snapshot_id(snapshot_id)
        if not re.fullmatch(r"evidence-[0-9a-f]{64}", evidence_ref):
            raise ValueError("invalid evidence reference")
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO evidence(snapshot_id,evidence_ref,payload) VALUES(?,?,?)",
                (snapshot_id, evidence_ref, payload),
            )

    def get_evidence(self, snapshot_id: str, evidence_ref: str) -> str | None:
        self._validate_snapshot_id(snapshot_id)
        if not re.fullmatch(r"evidence-[0-9a-f]{64}", evidence_ref):
            raise ValueError("invalid evidence reference")
        with self._transaction() as db:
            row = db.execute(
                "SELECT payload FROM evidence WHERE snapshot_id=? AND evidence_ref=?",
                (snapshot_id, evidence_ref),
            ).fetchone()
        return row["payload"] if row is not None else None


class ASTCacheStore(_SQLiteStore):
    """Persistent SQLite cache for deterministic AST intelligence keyed by (parser_version, extension, content_hash)."""

    def __init__(self, path: Path | str):
        super().__init__(
            path,
            """
            CREATE TABLE IF NOT EXISTS ast_cache (
                cache_key TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                file_path TEXT NOT NULL,
                facts TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """,
        )

    @staticmethod
    def cache_key(*, parser_version: str, extension: str, content_hash: str) -> str:
        raw = f"{parser_version}\0{extension}\0{content_hash}".encode("utf-8")
        return sha256(raw).hexdigest()

    def get_many(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with self._transaction() as db:
            rows = db.execute(
                f"SELECT cache_key, facts FROM ast_cache WHERE cache_key IN ({placeholders})",
                tuple(keys),
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                out[row["cache_key"]] = json.loads(row["facts"])
            except (ValueError, TypeError):
                continue
        return out

    def put_many(self, items: list[tuple[str, str, str, str, dict[str, Any]]]) -> None:
        if not items:
            return
        now = time.time()
        rows = [
            (key, content_hash, parser_version, file_path, json.dumps(facts, ensure_ascii=False), now)
            for key, content_hash, parser_version, file_path, facts in items
        ]
        with self._transaction() as db:
            db.executemany(
                "INSERT OR REPLACE INTO ast_cache(cache_key, content_hash, parser_version, file_path, facts, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                rows,
            )
