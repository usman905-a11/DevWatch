import fnmatch
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock, Thread
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Set, Tuple

from devwatch.config import Config
from devwatch.review.models import CommandSpec, RepositorySnapshot, ToolEvidence
from devwatch.scanner import IGNORED_DIRS, IGNORED_PATTERNS


_SECRET_ENV_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
_SAFE_EXECUTABLES = {
    "python",
    "python.exe",
    "python3",
    "pytest",
    "pytest.exe",
    "ruff",
    "ruff.exe",
    "mypy",
    "mypy.exe",
    "npm",
    "npm.cmd",
    "pnpm",
    "pnpm.cmd",
    "yarn",
    "yarn.cmd",
    "cargo",
    "cargo.exe",
    "go",
    "go.exe",
    "dotnet",
    "dotnet.exe",
}
_SHELL_EXECUTABLES = {
    "sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"
}
_SHELL_TOKENS = ("&&", "||", ";", "|", ">", "<", "$(", "`")
_INSTALL_ACTIONS = {"install", "add", "update", "upgrade", "ci"}


class WorkspaceSnapshotter:
    """Copy review inputs to an expendable run directory."""

    def __init__(self, runs_dir: str | Path):
        self.runs_dir = Path(runs_dir).resolve()

    def create(
        self,
        source_root: str | Path,
        job_id: str,
        content_sink: Optional[MutableMapping[str, str]] = None,
        content_paths: Optional[Set[str]] = None,
        materialize: bool = True,
        include_paths: Optional[Set[str]] = None,
    ) -> RepositorySnapshot:
        source = Path(source_root).resolve()
        if not source.is_dir():
            raise ValueError("snapshot source must be a directory")
        if not job_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in job_id):
            raise ValueError("job_id contains invalid characters")

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        target = (self.runs_dir / job_id).resolve()
        if target.parent != self.runs_dir:
            raise ValueError("snapshot target escaped the run directory")
        if target.exists():
            raise FileExistsError(f"snapshot already exists for {job_id}")
        target.mkdir()

        digest = hashlib.sha256()
        copied: List[str] = []
        content_hashes: Dict[str, str] = {}
        line_counts: Dict[str, int] = {}
        total_bytes = 0
        entries: List[Tuple[Path, Path, str]] = []
        for current_root, directory_names, file_names in os.walk(source):
            current = Path(current_root)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in IGNORED_DIRS and not name.startswith(".")
                and (current / name).resolve() != self.runs_dir
            )
            for file_name in sorted(file_names):
                path = current / file_name
                if path.is_symlink():
                    continue
                relative = path.relative_to(source)
                normalized = relative.as_posix()
                if include_paths is not None and normalized not in include_paths:
                    continue
                name = path.name.lower()
                if name in Config.BLOCKED_FILENAMES or name.startswith(".env"):
                    continue
                if any(
                    fnmatch.fnmatch(name, pattern)
                    for pattern in Config.BLOCKED_PATTERNS | IGNORED_PATTERNS
                ):
                    continue
                size = path.stat().st_size
                if size > Config.MAX_FILE_SIZE_BYTES:
                    continue
                total_bytes += size
                if total_bytes > Config.MAX_REPO_SIZE_BYTES:
                    raise ValueError("snapshot exceeds configured repository size limit")
                entries.append((path, relative, normalized))
                if len(entries) > Config.MAX_FILE_COUNT:
                    raise ValueError("snapshot exceeds configured file count limit")

        bundle = None
        bundle_index: Dict[str, List[int]] = {}
        if not materialize:
            bundle = (target / "artifacts.bin").open("wb")
        try:
            worker_count = min(32, max(4, (os.cpu_count() or 4) + 4))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                contents = executor.map(lambda entry: entry[0].read_bytes(), entries)
                for (_, relative, normalized), data in zip(entries, contents):
                    if bundle is not None:
                        offset = bundle.tell()
                        bundle.write(data)
                        bundle_index[normalized] = [offset, len(data)]
                    else:
                        destination = target / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)
                    digest.update(normalized.encode("utf-8"))
                    digest.update(data)
                    copied.append(normalized)
                    content_hashes[normalized] = hashlib.sha256(data).hexdigest()
                    if content_paths is None or normalized in content_paths:
                        decoded = data.decode("utf-8", errors="ignore")
                        line_counts[normalized] = max(1, len(decoded.splitlines()))
                        if content_sink is not None:
                            content_sink[normalized] = decoded
        finally:
            if bundle is not None:
                bundle.close()
                (target / "artifacts.index.json").write_text(
                    json.dumps(bundle_index, separators=(",", ":")),
                    encoding="utf-8",
                )

        return RepositorySnapshot(
            root_path=str(source),
            artifact_path=str(target),
            content_hash=digest.hexdigest(),
            files=copied,
            content_hashes=content_hashes,
            line_counts=line_counts,
        )

    def create_from_files(
        self, files: Mapping[str, str], job_id: str
    ) -> RepositorySnapshot:
        """Materialize uploaded source as bounded artifacts using safe relative paths."""
        if not job_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in job_id
        ):
            raise ValueError("job_id contains invalid characters")
        if len(files) > Config.MAX_FILES_PER_REVIEW:
            raise ValueError("uploaded review exceeds configured file limit")

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        target = (self.runs_dir / job_id).resolve()
        if target.parent != self.runs_dir:
            raise ValueError("artifact target escaped the run directory")
        if target.exists():
            raise FileExistsError(f"artifacts already exist for {job_id}")
        target.mkdir()

        digest = hashlib.sha256()
        copied: List[str] = []
        content_hashes: Dict[str, str] = {}
        line_counts: Dict[str, int] = {}
        total_bytes = 0
        for raw_path, content in sorted(files.items()):
            relative = Path(raw_path.replace("\\", "/"))
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ValueError(f"unsafe uploaded file path: {raw_path}")
            normalized = relative.as_posix()
            data = content.encode("utf-8")
            if len(data) > Config.MAX_FILE_SIZE_BYTES:
                raise ValueError(f"uploaded file exceeds configured size limit: {normalized}")
            total_bytes += len(data)
            if total_bytes > Config.MAX_REPO_SIZE_BYTES:
                raise ValueError("uploaded review exceeds configured repository size limit")
            destination = (target / relative).resolve()
            try:
                destination.relative_to(target)
            except ValueError as error:
                raise ValueError(f"unsafe uploaded file path: {raw_path}") from error
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            digest.update(normalized.encode("utf-8"))
            digest.update(data)
            copied.append(normalized)
            content_hashes[normalized] = hashlib.sha256(data).hexdigest()
            line_counts[normalized] = max(1, len(content.splitlines()))

        return RepositorySnapshot(
            root_path="uploaded_workspace",
            artifact_path=str(target),
            content_hash=digest.hexdigest(),
            files=copied,
            content_hashes=content_hashes,
            line_counts=line_counts,
        )

    def prune(self, retention_days: int) -> int:
        """Remove expired generated run directories without following links."""
        if retention_days < 0 or not self.runs_dir.is_dir():
            return 0
        cutoff = time.time() - (retention_days * 86400)
        removed = 0
        for candidate in self.runs_dir.iterdir():
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if resolved.parent != self.runs_dir:
                continue
            try:
                modified = candidate.stat().st_mtime
            except OSError:
                continue
            if modified > cutoff:
                continue
            shutil.rmtree(candidate)
            removed += 1
        return removed


class RestrictedCommandRunner:
    """Execute exact configured argv commands inside an expendable snapshot."""

    def __init__(
        self,
        allowed_commands: Iterable[CommandSpec],
        timeout_seconds: float = 120.0,
        max_output_bytes: int = 200_000,
    ):
        allowed_commands = list(allowed_commands)
        for command in allowed_commands:
            self._validate_command(command)
        self.allowed = {
            (tuple(command.argv), command.cwd): command for command in allowed_commands
        }
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    @staticmethod
    def _validate_command(command: CommandSpec) -> None:
        executable_path = Path(command.argv[0])
        executable = executable_path.name.lower()
        if executable in _SHELL_EXECUTABLES or executable not in _SAFE_EXECUTABLES:
            raise ValueError(f"executable is not allowed: {command.argv[0]}")
        if executable_path != Path(sys.executable).resolve() and (
            executable_path.is_absolute() or executable_path.parent != Path(".")
        ):
            raise ValueError(f"executable path is not allowed: {command.argv[0]}")
        if any(token in argument for argument in command.argv for token in _SHELL_TOKENS):
            raise ValueError("shell syntax is not allowed in review commands")
        for argument in command.argv[1:]:
            value = argument.split("=", 1)[-1]
            if ".." in value.replace("\\", "/").split("/"):
                raise ValueError("path traversal is not allowed in review commands")
            if Path(value).is_absolute():
                raise ValueError("absolute paths are not allowed in review command arguments")
        lowered = [argument.lower() for argument in command.argv[1:]]
        if any(action in _INSTALL_ACTIONS for action in lowered):
            raise ValueError("package installation commands are not allowed")
        if executable.startswith("python") and (
            "-c" in command.argv or lowered[:2] == ["-m", "pip"]
        ):
            raise ValueError("inline Python and package installation are not allowed")

    def run(self, snapshot: RepositorySnapshot, command: CommandSpec) -> ToolEvidence:
        if (tuple(command.argv), command.cwd) not in self.allowed:
            raise ValueError("command is not present in the exact allowlist")

        root = Path(snapshot.artifact_path).resolve()
        cwd = (root / command.cwd).resolve()
        try:
            cwd.relative_to(root)
        except ValueError as error:
            raise ValueError("command cwd escaped the snapshot") from error
        if not cwd.is_dir():
            raise ValueError("command cwd does not exist in the snapshot")

        executable = command.argv[0]
        if Path(executable) != Path(sys.executable).resolve():
            executable = shutil.which(executable)
            if executable is None:
                raise ValueError("review command executable was not found")
            resolved_executable = Path(executable).resolve()
            if resolved_executable.is_relative_to(root) or resolved_executable.is_relative_to(
                Path(snapshot.root_path).resolve()
            ):
                raise ValueError("review command executable is inside the reviewed workspace")

        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(part in key.upper() for part in _SECRET_ENV_PARTS)
            and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}
        }
        environment["PYTHONUNBUFFERED"] = "1"
        # Tests inside the snapshot can exercise DevWatch itself. Keep that
        # child review from starting another command runner recursively.
        environment["DEVWATCH_RUN_COMMANDS"] = "false"
        start = time.perf_counter()
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            [str(executable), *command.argv[1:]],
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        remaining = self.max_output_bytes
        capture_lock = Lock()
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        overflow = {"stdout": False, "stderr": False}

        def drain(name: str, stream) -> None:
            nonlocal remaining
            while chunk := stream.read(8192):
                with capture_lock:
                    keep = min(len(chunk), max(0, remaining))
                    captured[name].extend(chunk[:keep])
                    remaining -= keep
                    overflow[name] |= keep < len(chunk)
            stream.close()

        readers = [
            Thread(target=drain, args=(name, stream), daemon=True)
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_tree(process)
            process.wait()
        for reader in readers:
            reader.join(timeout=5)
        duration_ms = (time.perf_counter() - start) * 1000
        stdout = self._captured_text(captured["stdout"], overflow["stdout"])
        stderr = self._captured_text(captured["stderr"], overflow["stderr"])
        if timed_out:
            stderr = f"{stderr}\nCommand timed out after {self.timeout_seconds:g}s".strip()
        return ToolEvidence(
            source=command.name,
            summary=(
                f"{command.name} timed out"
                if timed_out
                else f"{command.name} exited with code {process.returncode}"
            ),
            command=command.argv,
            exit_code=-9 if timed_out else process.returncode,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            metadata={"cwd": command.cwd, "snapshot_hash": snapshot.content_hash},
        )

    @staticmethod
    def _captured_text(value: bytearray, truncated: bool) -> str:
        text = value.decode("utf-8", errors="replace")
        return text + ("\n[truncated]" if truncated else "")

    @staticmethod
    def _terminate_tree(process: subprocess.Popen) -> None:
        if os.name == "nt":
            import psutil

            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            try:
                for child in reversed(children):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
            finally:
                if process.poll() is None:
                    process.kill()
            _, alive = psutil.wait_procs(children, timeout=3)
            if alive:
                raise RuntimeError("timed-out review command left child processes running")
        else:
            os.killpg(process.pid, signal.SIGKILL)


def detect_commands(snapshot: RepositorySnapshot) -> List[CommandSpec]:
    """Return fixed argv commands for supported manifests with existing test scripts."""
    root = Path(snapshot.artifact_path)
    commands: List[CommandSpec] = []
    config_path = root / ".devwatch.toml"
    if config_path.is_file():
        try:
            config_data = tomllib.loads(config_path.read_text(encoding="utf-8"))
            configured = config_data.get("review", {}).get("commands", [])
            commands.extend(CommandSpec.model_validate(item) for item in configured)
        except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError):
            pass
    if (root / "pyproject.toml").is_file():
        commands.append(
            CommandSpec(
                name="pytest",
                argv=[sys.executable, "-m", "pytest", "-q"],
                cwd=".",
            )
        )
    for package_path in sorted(root.rglob("package.json")):
        if "node_modules" in package_path.parts:
            continue
        try:
            package_data = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not package_data.get("scripts", {}).get("test"):
            continue
        commands.append(
            CommandSpec(
                name="npm-test",
                argv=["npm", "test", "--silent"],
                cwd=package_path.parent.relative_to(root).as_posix() or ".",
            )
        )
    return commands
