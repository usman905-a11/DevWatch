"""Operator-approved exact commands; this trusted-host runner is not a sandbox."""
import asyncio
import codecs
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import time
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from devwatch.review.contracts import AGENT_CONTRACTS, AgentId, ContractModel
from devwatch.review.jobs import StepRenderInfo
from devwatch.review.stores import validate_source_path
from devwatch.review.subgraphs import ToolObservation

COMMAND_TOOLS = {"run_tests", "run_command", "lint", "type_check", "coverage", "sast", "profile", "benchmark", "db_analyze", "query_analyze"}
LIVE_STREAM_CAP_BYTES = 65536
COALESCE_INTERVAL_SECONDS = 0.2
COALESCE_BUFFER_BYTES = 4096


def _public_line(line: str) -> str:
    # Command output is untrusted. Raw output stays in owner-bound evidence.
    if (len(line) > 2048 or re.search(r"(?i)(api.?key|token|secret|password|credential|authorization|bearer)", line)
            or re.search(r"[A-Za-z0-9_-]{24,}", line)):
        return "[output redacted]\n"
    return line


class TrustedCommand(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    tool: Literal["run_tests", "run_command", "lint", "type_check", "coverage", "sast", "profile", "benchmark", "db_analyze", "query_analyze"]
    argv: tuple[str, ...] = Field(min_length=1, max_length=32)
    files: tuple[str, ...] = Field(min_length=1, max_length=100)
    timeout_seconds: float = Field(default=120, gt=0, le=120, allow_inf_nan=False)
    produces_measurement_artifact: bool = False

    @field_validator("argv")
    @classmethod
    def exact_executable(cls, value):
        executable = Path(value[0])
        if not executable.is_absolute() or not executable.is_file() or executable.name.lower() in {"cmd.exe", "powershell.exe", "pwsh.exe", "bash", "sh"}:
            raise ValueError("Trusted commands require an existing absolute non-shell executable")
        if any(not item or "\0" in item or len(item.encode()) > 2048 for item in value):
            raise ValueError("Command argv must be bounded")
        return value

    @field_validator("files")
    @classmethod
    def source_paths(cls, value):
        return tuple(validate_source_path(path) for path in value)

    @model_validator(mode="after")
    def measurement_scope(self):
        if self.produces_measurement_artifact and self.tool not in {"profile", "benchmark"}:
            raise ValueError("Only profiling/benchmark definitions grant measurement artifacts")
        return self


async def _drain(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def _kill_tree(process):
    if os.name == "nt":
        if process.returncode is not None:
            # The Windows job owns descendants even after the parent exits;
            # never look up a dead parent's potentially reused PID.
            await process.wait()
            return
        import psutil
        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        if process.returncode is None:
            process.kill()
        await process.wait()
        if children:
            _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=3)
            if alive:
                raise RuntimeError("Trusted command children did not drain")
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


class TrustedToolRuntime:
    def __init__(self, repository, jobs, job, *, commands=(), output_bytes=200_000):
        if not 1 <= output_bytes <= 200_000 or len(commands) > 100:
            raise ValueError("Trusted command/output registry must be bounded")
        self.repo, self.jobs, self.job = repository, jobs, job
        self.commands = {command.command_id: command for command in commands}
        if len(self.commands) != len(commands):
            raise ValueError("Duplicate trusted command ID")
        self.output_bytes = output_bytes
        self.active_processes = 0

    def grants_measurement(self, task):
        return task.agent_id == AgentId.PERFORMANCE_SCALABILITY and any(
            command.produces_measurement_artifact and set(command.files).issubset(task.files) for command in self.commands.values())

    async def write_measurement(self, arguments, task):
        if not self.grants_measurement(task) or set(arguments) != {"evidence_ref"}:
            raise PermissionError("Measurement artifact requires an explicit task grant and evidence reference")
        reference = arguments["evidence_ref"]
        record = self.repo.scoped_evidence(reference, task)
        measurement = record.get("data")
        definition = self.commands.get(measurement.get("command_id")) if isinstance(measurement, dict) else None
        if (record.get("tool") not in {"profile", "benchmark"} or definition is None or not definition.produces_measurement_artifact
                or not self.jobs.owns_tool_evidence(self.job.job_id, owner=self.job.owner, task_id=task.task_id, evidence_ref=reference)):
            raise PermissionError("Measurement evidence does not belong to the approved job/task")
        encoded = json.dumps({"snapshot_id": self.repo.snapshot_id, "job_id": self.job.job_id, "task_id": task.task_id,
                              "evidence_ref": reference, "measurement": record["data"]}, sort_keys=True).encode()
        identity = "measurement-" + sha256(encoded).hexdigest()
        owner = sha256(self.job.owner.encode()).hexdigest()
        root = self.repo.artifacts.root / "measurements" / owner / self.job.job_id
        root.mkdir(parents=True, exist_ok=True)
        destination = root / (identity + ".json")
        # Runtime owns the destination and complete serializer, never the model.
        with self.jobs.publication(self.job.job_id, owner=self.job.owner):
            if destination.exists():
                if destination.read_bytes() != encoded:
                    raise ValueError("Measurement artifact integrity mismatch")
            else:
                from uuid import uuid4
                temporary = root / (identity + "." + uuid4().hex + ".tmp")
                try:
                    with temporary.open("xb") as stream:
                        stream.write(encoded)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        return self.repo._record({"tool": "write_artifact", "source_scope": record["source_scope"],
                                  "data": {"artifact_ref": identity}}, work=task)

    async def execute(self, task, action, *, progress=None, step_handle=None):
        AGENT_CONTRACTS[task.agent_id].validate_action(action)
        if set(action.arguments) != {"command_id"}:
            raise ValueError("Command tools accept only an approved command_id")
        command = self.commands.get(action.arguments["command_id"])
        if command is None or command.tool != action.tool or not set(command.files).issubset(task.files):
            raise PermissionError("Command is not approved for this tool/task scope")
        executable = Path(command.argv[0]).resolve()
        if executable.is_relative_to(self.repo.artifacts.root):
            raise PermissionError("Executable cannot belong to reviewed artifacts")
        command_str = " ".join(Path(command.argv[0]).name if idx == 0 else arg for idx, arg in enumerate(command.argv))[:512]
        digest = sha256(json.dumps({"definition": command.model_dump(mode="json"), "snapshot": self.repo.manifest.content_hash}, sort_keys=True).encode()).hexdigest()
        operation_id, previous = self.jobs.admit_tool_operation(self.job.job_id, owner=self.job.owner,
            task_id=task.task_id, command_id=command.command_id, input_hash=digest)
        if previous:
            self.repo.scoped_evidence(previous, task)
            info = StepRenderInfo(command=command_str, evidence_ref=previous, files=list(command.files)[:25])
            if step_handle is not None:
                step_handle.set_completion_info(info)
            return ToolObservation(evidence_ref=previous, inspected=list(command.files), render_info=info)
        if step_handle is not None:
            step_handle.set_completion_info({"command": command_str, "files": list(command.files)[:25]})
        scratch = self.repo.artifacts.create_scratch(self.repo.snapshot_id, owner=self.repo.owner, files=list(command.files))
        # Only explicitly assigned files are materialized for this command.
        # The source copy is disposable; original and immutable files stay intact.
        environment = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        environment.update(PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1", LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
        started = time.monotonic()
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(*command.argv, cwd=scratch, env=environment,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt", creationflags=(0x08000000 | 0x00000200 | 0x00000004) if os.name == "nt" else 0))
        process = None
        process_job = None
        readers = []
        coalescer = None
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        remaining, truncated, timed_out = self.output_bytes, False, False
        public_remaining = 16000
        step_buffers: dict[str, list[str]] = {"stdout": [], "stderr": []}
        step_buffered_bytes = 0
        step_streamed_bytes = 0
        step_truncated = False
        flush_lock = asyncio.Lock()

        async def flush_step_deltas() -> None:
            nonlocal step_buffered_bytes
            if step_handle is None:
                return
            async with flush_lock:
                out_chunk = "".join(step_buffers["stdout"])
                err_chunk = "".join(step_buffers["stderr"])
                step_buffers["stdout"].clear()
                step_buffers["stderr"].clear()
                step_buffered_bytes = 0
                patch: dict[str, str] = {}
                if out_chunk:
                    patch["stdout_append"] = out_chunk
                if err_chunk:
                    patch["stderr_append"] = err_chunk
                if patch:
                    await step_handle.emit_delta(patch)

        async def periodic_flush() -> None:
            while True:
                await asyncio.sleep(COALESCE_INTERVAL_SECONDS)
                if step_buffers["stdout"] or step_buffers["stderr"]:
                    await flush_step_deltas()

        async def read(name, stream):
            nonlocal remaining, truncated, public_remaining, step_buffered_bytes, step_streamed_bytes, step_truncated
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            pending = ""
            redact_until_newline = False

            async def publish(line):
                nonlocal public_remaining, step_buffered_bytes, step_streamed_bytes, step_truncated
                redacted = _public_line(line)
                if progress is not None and public_remaining > 0:
                    safe = redacted[:public_remaining]
                    public_remaining -= len(safe)
                    if safe:
                        await progress(name, safe)
                if step_handle is not None and redacted:
                    if step_streamed_bytes >= LIVE_STREAM_CAP_BYTES:
                        step_truncated = True
                        return
                    raw_bytes = redacted.encode("utf-8")
                    allowed_bytes = LIVE_STREAM_CAP_BYTES - step_streamed_bytes
                    if len(raw_bytes) > allowed_bytes:
                        redacted = raw_bytes[:allowed_bytes].decode("utf-8", errors="ignore")
                        raw_bytes = redacted.encode("utf-8")
                        step_truncated = True
                    if redacted:
                        step_buffers[name].append(redacted)
                        step_buffered_bytes += len(raw_bytes)
                        step_streamed_bytes += len(raw_bytes)
                        if step_buffered_bytes >= COALESCE_BUFFER_BYTES:
                            await flush_step_deltas()

            while chunk := await stream.read(8192):
                keep = min(remaining, len(chunk))
                captured[name].extend(chunk[:keep])
                remaining -= keep
                truncated |= keep < len(chunk)
                if (progress is not None or step_handle is not None) and keep:
                    pending += decoder.decode(chunk[:keep])
                    if redact_until_newline:
                        if "\n" not in pending:
                            pending = ""
                            continue
                        pending = pending.split("\n", 1)[1]
                        redact_until_newline = False
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        await publish(line + "\n")
                    if len(pending) > 2048:
                        await publish("[output redacted]\n")
                        pending = ""
                        redact_until_newline = True
            if (progress is not None or step_handle is not None) and pending and not redact_until_newline:
                await publish(pending)
        try:
            process = await asyncio.shield(spawn)
            if os.name == "nt":
                from devwatch.review.windows_process_job import WindowsProcessJob
                process_job = WindowsProcessJob(process)
            self.active_processes += 1
            if step_handle is not None:
                coalescer = asyncio.create_task(periodic_flush())
            readers = [asyncio.create_task(read(name, stream)) for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))]
            current = self.jobs.get(self.job.job_id, owner=self.job.owner)
            timeout = min(command.timeout_seconds, max(.001, current.limits.review_seconds - current.ledger.elapsed_seconds))
            async def parent_exit():
                # Process.wait also waits for pipe transport closure. An exited
                # parent may have children holding those pipes; detect exit first
                # so owned descendants are killed before draining output.
                while process.returncode is None:
                    await asyncio.sleep(.01)
            try:
                await asyncio.wait_for(parent_exit(), timeout)
            except TimeoutError:
                timed_out = True
            if process_job is not None:
                process_job.close()
            await _kill_tree(process)
            await asyncio.wait_for(asyncio.gather(*readers), 3)
            if coalescer is not None:
                coalescer.cancel()
                await asyncio.gather(coalescer, return_exceptions=True)
                coalescer = None
            await flush_step_deltas()
        finally:
            if coalescer is not None:
                coalescer.cancel()
                await _drain(asyncio.ensure_future(asyncio.gather(coalescer, return_exceptions=True)))
            if process is None:
                process = await _drain(spawn)
            if process_job is not None:
                process_job.close()
            cleanup = asyncio.create_task(_kill_tree(process))
            await _drain(cleanup)
            for reader in readers:
                reader.cancel()
            if readers:
                await _drain(asyncio.ensure_future(asyncio.gather(*readers, return_exceptions=True)))
            self.active_processes = max(0, self.active_processes - 1)
        data = {"command_id": command.command_id, "exit_code": process.returncode, "timed_out": timed_out,
                "truncated": truncated, "duration_seconds": time.monotonic() - started,
                **{name: value.decode("utf-8", errors="replace") for name, value in captured.items()}}
        observation = self.repo._record({"tool": command.tool, "source_scope": list(command.files),
            "inspected": list(command.files), "data": data, "limitations": ["Trusted host execution is not a security sandbox"]}, work=task)
        self.jobs.complete_tool_operation(self.job.job_id, owner=self.job.owner, operation_id=operation_id, evidence_ref=observation.evidence_ref)
        is_truncated = bool(truncated or step_truncated)
        render_info = StepRenderInfo(
            command=command_str,
            exit_code=process.returncode,
            truncated=is_truncated,
            output_truncated=is_truncated,
            files=list(command.files)[:25],
            evidence_ref=observation.evidence_ref,
        )
        if step_handle is not None:
            step_handle.set_completion_info(render_info)
            if timed_out or process.returncode not in (None, 0):
                step_handle.mark_error(
                    "Command timed out" if timed_out else f"Command exited with code {process.returncode}",
                    render_info,
                )
        return observation.model_copy(update={"render_info": render_info})
