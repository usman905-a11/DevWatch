"""M10 test utilities: real local HTTP/runtime, with only model output scripted."""
import asyncio
from collections import Counter
from contextlib import contextmanager
import json
import os
import socket
import subprocess
import threading
import time
from urllib.request import ProxyHandler, build_opener

import uvicorn

from devwatch.providers.base import LLMResponse, LLMUsage
from devwatch.review.capture import capture_source
from devwatch.review.client import ReviewClient, _NoRedirect
from devwatch.review.contracts import ModelTier
from devwatch.review.service import ServiceSettings, create_app


KEY = "m10-local-fixture-key"
FILES = {
    "logic_correctness": "logic.py",
    "bug_reliability": "reliability.py",
    "quality_testability": "quality.py",
    "architecture_security": "security.py",
    "performance_scalability": "performance.py",
}


def repository(path, *, large=False):
    path.mkdir()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(["git", "-c", "init.templateDir=", "init", "--quiet", str(path)], env=environment,
                   capture_output=True, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for role, filename in FILES.items():
        source = "def first(items):\n    return items[0]\n" if role == "logic_correctness" else "def identity(value):\n    return value\n"
        if large and role == "quality_testability":
            source = "\n".join(f"def identity_{i}(value):\n    return value\n" for i in range(400))
        (path / filename).write_text(source, encoding="utf-8")
    capture = capture_source(path)
    assert set(capture.files) == set(FILES.values())
    assert set(capture.changed_files) == set(FILES.values())
    return capture


class ScenarioProvider:
    """Complete typed responses; runtime, validation and tool effects stay real."""
    def __init__(self, mode="normal"):
        self.mode = mode
        self.observed = []
        self.counts = Counter()
        self.entered, self.drained = threading.Event(), threading.Event()

    async def generate_completion(self, request):
        body = json.loads(request.prompt)
        role, phase = body["task"]["agent_id"], body["phase"]
        self.counts[role, phase] += 1
        step = self.counts[role, phase]
        self.observed.append({"role": role, "phase": phase, "repair": body["repair"] is not None,
            "omissions": body["context_omissions"], "request_bound": len(request.prompt.encode()) +
                len(request.system_prompt.encode()) + 512 + request.max_tokens})
        if self.mode in {"pause", "deadline"} and role == "synthesizer_verifier" and phase == "synthesis":
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.drained.set()
        if self.mode == "provider_timeout" and role == "bug_reliability":
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.drained.set()
        action = self.action(body, step)
        content = json.dumps(action)
        if role == "bug_reliability" and self.mode in {"malformed", "malformed_exhausted"}:
            if step == 1 or self.mode == "malformed_exhausted":
                content = "{"
        if phase == "synthesis" and self.mode in {"final_repair", "final_repair_exhausted"}:
            if step == 1 or self.mode == "final_repair_exhausted":
                # Schema-valid draft deliberately drops the recorded confirmed
                # finding. Runtime consistency repair must preserve verification.
                content = json.dumps({"kind": "submit_synthesis", "payload": {
                    **body["verified"], "report_draft": {"snapshot_id": body["selected_context"]["snapshot_id"],
                        "summary": "Dropped a recorded finding", "coverage": {}}, "coverage_summary": {}}})
        return LLMResponse(content=content,
            finish_reason="length" if self.mode == "truncated" and role == "bug_reliability" else "stop",
            provider="scripted", model=request.model, latency_ms=0,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    def action(self, body, step):
        role, phase = body["task"]["agent_id"], body["phase"]
        private = body["private_state"]
        if role == "planner":
            if not private["evidence_refs"]:
                action = {"kind": "call_tool", "tool": "repo_map", "arguments": {}}
            else:
                action = {"kind": "submit_plan", "payload": {
                    "selected_agents": list(FILES), "priority_files": list(FILES.values()),
                    "priority_symbols": [], "risk_areas": ["fixture boundary"],
                    "review_tasks": [{"task_id": agent, "agent_id": agent, "files": [filename], "focus": "Inspect assigned source"}
                                     for agent, filename in FILES.items()],
                    "review_strategy": "Inspect each file independently", "coverage_expectations": list(FILES.values())}}
        elif role in FILES:
            path = FILES[role]
            if role == "bug_reliability" and step == 1 and self.mode in {"tool_failure", "invalid_arguments"}:
                arguments = {"file_path": path, "start_line": 999, "end_line": 1000} if self.mode == "tool_failure" else {"unexpected": "private-m10-error"}
                action = {"kind": "call_tool", "tool": "read_source", "arguments": arguments}
            elif role == "performance_scalability" and step == 1 and self.mode in {"unavailable", "unapproved"}:
                action = {"kind": "call_tool", "tool": "benchmark", "arguments": {"command_id": "not-configured"}}
            elif role == "quality_testability" and self.mode == "oversized" and step <= 3:
                if step == 1:
                    action = {"kind": "call_tool", "tool": "parse_ast", "arguments": {"file_path": path}}
                elif step == 2:
                    action = {"kind": "call_tool", "tool": "read_evidence", "arguments": {
                        "evidence_ref": private["evidence_refs"][0], "offset": 12000, "max_chars": 1000}}
                else:
                    action = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": path, "start_line": 1, "end_line": 2}}
            elif role == 'bug_reliability' and self.mode == 'budget' and private['evidence_refs']:
                # Distinct page requests exercise the global iteration ceiling;
                # an identical acknowledged source read stops as no_progress.
                action = {'kind': 'call_tool', 'tool': 'read_evidence', 'arguments': {
                    'evidence_ref': private['evidence_refs'][0], 'offset': step - 1, 'max_chars': 1}}
            elif not private["evidence_refs"]:
                action = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": path}}
            else:
                candidates = []
                if role == "logic_correctness":
                    candidates = [{"category": "logic", "title": "Empty input raises", "description": "Index zero is read without an empty check",
                        "impact": "Empty input raises IndexError", "confidence": .9, "evidence_refs": private["evidence_refs"],
                        "location": {"snapshot_id": body["selected_context"]["snapshot_id"], "file_path": path, "start_line": 2, "end_line": 2}}]
                action = {"kind": "submit_candidates", "payload": {"task_id": role, "agent_id": role,
                    "candidates": candidates, "coverage": {}, "stop_reason": "evidence_complete"}}
        elif phase == "verification":
            if not private["evidence_refs"]:
                action = {"kind": "call_tool", "tool": "read_source", "arguments": {"file_path": "logic.py", "start_line": 2, "end_line": 2}}
            else:
                action = {"kind": "submit_verification", "payload": {"decisions": [{
                    "finding_id": identity, "verdict": "confirmed", "confidence": .9,
                    "rationale": "Scoped source inspection establishes direct indexing of possibly empty input",
                    "evidence_refs": [private["evidence_refs"][-1]]} for identity in body["candidates"]]}}
        else:
            action = {"kind": "submit_synthesis", "payload": {"summary": "One source-backed boundary defect", "limitations": []}}
        action["inspected_evidence"] = [page["evidence_ref"] for page in body["selected_context"].get("evidence", [])]
        return action


@contextmanager
def live_runtime(root, provider):
    """Bind an ephemeral loopback port; always drain service before returning."""
    app = create_app(settings=ServiceSettings(runtime_root=root, models={tier: tier.value for tier in ModelTier},
                                             api_keys=frozenset({KEY})), provider=provider)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, loop="asyncio", ws="none", lifespan="on",
        log_config=None, log_level="critical", access_log=False, timeout_graceful_shutdown=.2))
    errors = []

    def run():
        try:
            server.run(sockets=[listener])
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if errors:
                raise errors[0]
            if not worker.is_alive() or time.monotonic() >= deadline:
                raise AssertionError("local fixture service did not start")
            time.sleep(.01)
        client = ReviewClient(f"http://127.0.0.1:{port}", api_key=KEY,
                              opener=build_opener(ProxyHandler({}), _NoRedirect()).open)
        yield client, app
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
        assert not worker.is_alive(), "local fixture service failed to drain"
        if errors:
            raise errors[0]


def timeline(client, job_id):
    events, cursor = [], 0
    for _ in range(100):
        page = client.events(job_id, after=cursor)
        if not page["events"]:
            return events
        events.extend(page["events"])
        cursor = page["next_cursor"]
    raise AssertionError("fixture timeline exceeded its bounded replay pages")
