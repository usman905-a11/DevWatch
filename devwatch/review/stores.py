"""Separated local store locations, immutable source snapshots and versioned cache."""

from dataclasses import dataclass
import fnmatch
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from devwatch.config import Config
from devwatch.review.contracts import ContractModel, SourceLocation
from devwatch.review.jobs import _SQLiteStore


@dataclass(frozen=True)
class StoreLayout:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def jobs(self) -> Path:
        return self.root / "jobs.sqlite"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints.sqlite"

    @property
    def repo_cache(self) -> Path:
        return self.root / "repo-cache.sqlite"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def events(self) -> Path:
        return self.root / "events.sqlite"


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
    for part in Path(name).parts:
        if (part.lower().startswith(".env") or part.lower() in excluded
                or part.lower() in Config.BLOCKED_FILENAMES
                or any(fnmatch.fnmatch(part.lower(), pattern) for pattern in Config.BLOCKED_PATTERNS)):
            raise ValueError("sensitive or generated source path is excluded")
    return name


class ArtifactStore:
    """Only capture creates source snapshots. There is no source-write API.

    Local operators can alter disk contents; reads detect tampering rather than
    treating the host filesystem as a security boundary. Commands use scratch.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        for directory in ("snapshots", "scratch", "reports"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    def _snapshot_dir(self, snapshot_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id):
            raise ValueError("invalid snapshot identity")
        path = (self.root / "snapshots" / snapshot_id).resolve()
        if not path.is_relative_to(self.root / "snapshots"):
            raise ValueError("snapshot path escaped the Artifact Store")
        return path

    def capture(self, *, owner: str, files: dict[str, str], capture_coverage: CaptureCoverage | None = None,
                git_metadata: GitMetadata | None = None) -> SnapshotManifest:
        if not owner or len(owner) > 256:
            raise ValueError("bounded snapshot owner is required")
        if len(files) > Config.MAX_FILES_PER_REVIEW:
            raise ValueError("snapshot file count exceeded")
        entries, encoded, identities = {}, {}, set()
        for raw_path, content in files.items():
            path = validate_source_path(raw_path)
            identity = os.path.normcase(path)
            if identity in identities:
                raise ValueError("duplicate normalized source path")
            identities.add(identity)
            data = content.encode("utf-8")
            if len(data) > Config.MAX_BYTES_PER_FILE:
                raise ValueError("snapshot file size exceeded")
            encoded[path] = data
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
        final = self._snapshot_dir(manifest.snapshot_id)
        staging = self.root / "snapshots" / f"pending-{manifest.snapshot_id}"
        staging.mkdir()
        for path, data in encoded.items():
            destination = staging / "source" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (staging / "source").mkdir(exist_ok=True)
        (staging / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        # Same-volume directory rename publishes a complete immutable snapshot.
        os.replace(staging, final)
        return manifest

    def manifest(self, snapshot_id: str, *, owner: str) -> SnapshotManifest:
        directory = self._snapshot_dir(snapshot_id)
        manifest = SnapshotManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.owner != owner:
            raise PermissionError("snapshot is not owned by this principal")
        if (manifest.snapshot_id != snapshot_id or _content_hash(manifest.entries) != manifest.content_hash
                or _capture_hash(manifest.capture_coverage) != manifest.capture_hash
                or _git_hash(manifest.git_metadata) != manifest.git_hash):
            raise SnapshotIntegrityError("snapshot manifest identity mismatch")
        return manifest

    def source_root(self, snapshot_id: str, *, owner: str) -> Path:
        self.manifest(snapshot_id, owner=owner)
        return self._snapshot_dir(snapshot_id) / "source"

    def read_source(self, snapshot_id: str, file_path: str, *, owner: str) -> str:
        manifest = self.manifest(snapshot_id, owner=owner)
        file_path = validate_source_path(file_path)
        entry = manifest.entries.get(file_path)
        if entry is None:
            raise FileNotFoundError("source was not captured in this snapshot")
        root = self._snapshot_dir(snapshot_id) / "source"
        path = (root / file_path).resolve()
        if not path.is_relative_to(root):
            raise SnapshotIntegrityError("snapshot source escaped its root")
        data = path.read_bytes()
        if len(data) != entry.byte_count or sha256(data).hexdigest() != entry.content_hash:
            raise SnapshotIntegrityError("snapshot source content changed")
        return data.decode("utf-8")

    def create_scratch(self, snapshot_id: str, *, owner: str, files: list[str] | None = None) -> Path:
        manifest = self.manifest(snapshot_id, owner=owner)
        # Read and validate the entire snapshot before creating a command workspace.
        selected = list(manifest.entries) if files is None else files
        if any(name not in manifest.entries for name in selected):
            raise PermissionError("Scratch source must belong to the captured snapshot")
        contents = {name: self.read_source(snapshot_id, name, owner=owner) for name in selected}
        scratch = self.root / "scratch" / uuid4().hex
        scratch.mkdir()
        for name, content in contents.items():
            destination = scratch / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content.encode("utf-8"))
        return scratch

    def _report_pdf_path(self, job_id: str, reference: str, *, owner: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not re.fullmatch(r"[0-9a-f]{64}", reference):
            raise ValueError("invalid report artifact identity")
        path = (self.root / "reports" / sha256(owner.encode("utf-8")).hexdigest() / job_id / f"{reference}.pdf").resolve()
        if not path.is_relative_to(self.root / "reports"):
            raise SnapshotIntegrityError("report artifact escaped the Artifact Store")
        return path

    def put_report_pdf(self, job_id: str, snapshot_id: str, *, owner: str, data: bytes) -> str:
        self.manifest(snapshot_id, owner=owner)
        if (not isinstance(data, bytes) or len(data) > 10_000_000
                or not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF")):
            raise ValueError("bounded PDF bytes required")
        reference = sha256(data).hexdigest()
        path = self._report_pdf_path(job_id, reference, owner=owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f"pending-{uuid4().hex}"
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return reference

    def read_report_pdf(self, job_id: str, snapshot_id: str, *, owner: str, reference: str) -> bytes:
        self.manifest(snapshot_id, owner=owner)
        with self._report_pdf_path(job_id, reference, owner=owner).open("rb") as stream:
            data = stream.read(10_000_001)
        if len(data) > 10_000_000 or sha256(data).hexdigest() != reference:
            raise SnapshotIntegrityError("report artifact content changed")
        return data


class CacheConflict(ValueError):
    pass


class CacheKey(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_namespace: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    parser_version: str = ""
    analysis_config_hash: str = ""
    prompt_version: str = ""
    model_name: str = ""
    schema_version: str = "seven-agent-v1"

    @property
    def digest(self) -> str:
        return sha256(_canonical_json(self.model_dump(mode="json")).encode("utf-8")).hexdigest()


class RepoCache(_SQLiteStore):
    def __init__(self, path: Path | str):
        super().__init__(path, "CREATE TABLE IF NOT EXISTS cache (digest TEXT PRIMARY KEY, payload TEXT NOT NULL);")
        with self._transaction() as db:
            if "last_used" not in {row[1] for row in db.execute("PRAGMA table_info(cache)")}:
                db.execute("ALTER TABLE cache ADD COLUMN last_used REAL NOT NULL DEFAULT 0")
                db.execute("UPDATE cache SET last_used=?", (time.time(),))

    def put(self, key: CacheKey, value) -> None:
        payload = _canonical_json(value)
        if len(payload.encode("utf-8")) > 10_000_000:
            raise ValueError("cache payload exceeds local limit")
        with self._transaction() as db:
            previous = db.execute("SELECT payload FROM cache WHERE digest=?", (key.digest,)).fetchone()
            if previous is not None:
                if previous[0] != payload:
                    raise CacheConflict("same cache identity produced different content")
                db.execute("UPDATE cache SET last_used=? WHERE digest=?", (time.time(), key.digest))
                return
            db.execute("INSERT INTO cache(digest,payload,last_used) VALUES(?,?,?)", (key.digest, payload, time.time()))

    def get(self, key: CacheKey):
        with self._transaction() as db:
            row = db.execute("SELECT payload FROM cache WHERE digest=?", (key.digest,)).fetchone()
            if row is not None:
                db.execute("UPDATE cache SET last_used=? WHERE digest=?", (time.time(), key.digest))
            return json.loads(row[0]) if row else None
