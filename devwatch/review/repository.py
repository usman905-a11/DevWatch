"""Snapshot-bound intelligence, selective context and evidence reducers.

Python AST facts are deterministic. Languages without an installed parser are
reported explicitly; lexical search is never presented as an AST or type check.
Only this runtime creates evidence artifacts. Agents receive references, not
destinations or access to another task's private state.
"""

from functools import partial
from hashlib import sha256
import json
from pathlib import Path
import re
import tomllib
from typing import Any
from uuid import uuid4

from devwatch.config import Config
from devwatch.review.contracts import CandidateRejection, Coverage, FindingCandidate, ReviewTask, SpecialistResult
from devwatch.review.stores import ArtifactStore, CacheKey, RepoCache, validate_source_path
from devwatch.review.subgraphs import PermissionedTools, ToolObservation
from devwatch.review.tool_errors import ToolFailure
from devwatch.review.intelligence import PARSER_VERSION, analyze_source, import_edges


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class RepositoryContext:
    CONTEXT_BYTES = 6000

    def __init__(self, artifacts: ArtifactStore, cache: RepoCache, snapshot_id: str, *, owner: str):
        self.artifacts, self.cache, self.snapshot_id, self.owner = artifacts, cache, snapshot_id, owner
        self.manifest = artifacts.manifest(snapshot_id, owner=owner)
        self.evidence_root = artifacts.root / "evidence" / snapshot_id
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self._analysis = None

    def _source(self, path):
        try:
            return self.artifacts.read_source(self.snapshot_id, path, owner=self.owner)
        except (ValueError, FileNotFoundError) as exc:
            raise ToolFailure("snapshot_integrity_failure", "Stop: captured source integrity could not be verified.",
                              recoverable=False, arguments={"file_path": path}) from exc

    def analyze(self) -> dict[str, Any]:
        if self._analysis is not None:
            return self._analysis
        result = {}
        for path, entry in sorted(self.manifest.entries.items()):
            # Integrity is checked even on cache hits.
            source = self._source(path)
            key = CacheKey(owner_namespace=self.owner, namespace="repository-intelligence",
                           content_hash=entry.content_hash, parser_version=PARSER_VERSION,
                           analysis_config_hash=Path(path).suffix.lower())
            facts = self.cache.get(key)
            if facts is None:
                facts = analyze_source(path, source)
                self.cache.put(key, facts)
            result[path] = facts
        self._analysis = result
        return result

    def _scoped_path(self, value, work) -> str:
        path = validate_source_path(value)
        if path not in work.files or path not in self.manifest.entries:
            raise PermissionError("source is outside the assigned scope")
        return path

    def _record(self, payload: dict[str, Any], *, work=None) -> ToolObservation:
        scope = payload.get("source_scope", [payload["file_path"]] if payload.get("file_path") else [])
        record = {"snapshot_id": self.snapshot_id, "snapshot_hash": self.manifest.content_hash,
                  "source_scope": sorted(set(scope)), **payload}
        if work is not None:
            record["provenance"] = {"agent_id": work.agent_id.value, "task_id": work.task_id}
        encoded = _json(record)
        identity = "evidence-" + sha256(encoded.encode("utf-8")).hexdigest()
        destination = self.evidence_root / (identity + ".json")
        temporary = self.evidence_root / ("pending-" + uuid4().hex)
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(destination)
        return ToolObservation(evidence_ref=identity, inspected=payload.get("inspected", [payload["file_path"]] if payload.get("file_path") else []))

    def scoped_evidence(self, identity: str, work) -> dict[str, Any]:
        record = self.evidence(identity)
        if not set(record["source_scope"]).issubset(work.files):
            raise PermissionError("evidence is outside the assigned scope")
        return record

    def evidence(self, identity: str) -> dict[str, Any]:
        if not re.fullmatch(r"evidence-[0-9a-f]{64}", identity):
            raise ValueError("invalid evidence reference")
        try:
            record = json.loads((self.evidence_root / (identity + ".json")).read_text(encoding="utf-8"))
            encoded = _json(record)
        except FileNotFoundError as exc:
            raise ToolFailure("evidence_not_found", "Use an evidence_ref returned by a tool in this snapshot.",
                              arguments={"evidence_ref": identity}) from exc
        except (ValueError, UnicodeError) as exc:
            raise ToolFailure("evidence_integrity_failure", "Stop: evidence integrity could not be verified.",
                              recoverable=False, arguments={"evidence_ref": identity}) from exc
        expected = "evidence-" + sha256(encoded.encode("utf-8")).hexdigest()
        if (not isinstance(record, dict) or expected != identity
                or record.get("snapshot_id") != self.snapshot_id
                or record.get("snapshot_hash") != self.manifest.content_hash
                or not isinstance(record.get("source_scope"), list)
                or any(not isinstance(path, str) or path not in self.manifest.entries for path in record["source_scope"])):
            raise ToolFailure("evidence_integrity_failure", "Stop: evidence integrity could not be verified.",
                              recoverable=False, arguments={"evidence_ref": identity})
        for path in record["source_scope"]:
            self._source(path)
        return record

    def _read_source(self, arguments, work):
        if set(arguments) - {"file_path", "start_line", "end_line"}:
            raise ValueError("unsupported source arguments")
        path = self._scoped_path(arguments.get("file_path"), work)
        source = self._source(path)
        lines = source.splitlines()
        start = arguments.get("start_line", 1)
        end = arguments.get("end_line")
        if end is None and type(start) is int:
            end = start + 79
        if (type(start) is not int or type(end) is not int or start < 1 or end < start
                or start > max(1, len(lines)) or end - start >= 200):
            raise ToolFailure("invalid_source_range",
                "Choose start_line within the captured line_count and request at most 200 lines; "
                "omit end_line for up to 80 lines. Empty files accept start_line=1.",
                details={"line_count": len(lines), "max_lines": 200})
        if not lines:
            return self._record({"tool": "read_source", "file_path": path, "line_count": 0,
                                 "content_hash": self.manifest.entries[path].content_hash, "data": ""}, work=work)
        # A bounded request may extend past EOF; report only the actual source
        # range rather than making the agent guess a short file's line count.
        end = min(end, len(lines))
        excerpt = "\n".join(lines[start - 1:end])
        return self._record({"tool": "read_source", "file_path": path, "start_line": start,
                             "end_line": end, "content_hash": self.manifest.entries[path].content_hash,
                             "data": excerpt}, work=work)

    def _read_sources(self, arguments, work):
        from devwatch.review.tool_catalogue import SourceArguments
        parsed = SourceArguments.model_validate(arguments).model_dump(exclude_unset=True)
        paths = [parsed.pop('file_path'), *parsed.pop('additional_files', [])]
        # Authorize the entire batch before materializing any source artifact.
        for path in paths:
            self._scoped_path(path, work)
        observations = [self._read_source({**parsed, 'file_path':path}, work) for path in paths]
        return observations[0].model_copy(update={
            'additional_evidence_refs':[item.evidence_ref for item in observations[1:]]})

    def evidence_page(self, identity, work, *, offset=0, max_chars=1500):
        record = self.scoped_evidence(identity, work)
        encoded = _json(record)
        if type(offset) is not int or not 0 <= offset < len(encoded):
            raise ToolFailure("invalid_evidence_offset", "Choose offset below total_chars; use next_offset for later pages.",
                              details={"total_chars": len(encoded)})
        end = min(len(encoded), offset + max_chars)
        page = {"evidence_ref": identity, "offset": offset, "end_offset": end,
                "source_file": record.get("file_path") if record.get("tool") == "read_source" else None,
                "total_chars": len(encoded), "next_offset": end if end < len(encoded) else None,
                "source_scope": record["source_scope"] if len(_json(record["source_scope"]).encode("utf-8")) <= 512 else [],
                "scope_count": len(record["source_scope"]), "provenance": record.get("provenance", {}),
                "excerpt": encoded[offset:end]}
        while len(_json(page).encode("utf-8")) > 2800:
            end = offset + (end - offset) // 2
            if end <= offset:
                raise ValueError("evidence scope metadata exceeds page budget")
            page.update(end_offset=end, next_offset=end, excerpt=encoded[offset:end])
        return page

    def context(self, state):
        work, private, action = state["task"], state["private_state"], state.get("action")
        if action is not None and action.kind == "request_context":
            return self._read_sources(action.arguments, work)
        pages = [self.evidence_page(identity, work, offset=private.evidence_cursors.get(identity, 0),
                                   max_chars=private.evidence_page_sizes.get(identity, 1500))
                 for identity in reversed(list(dict.fromkeys(work.evidence_refs + private.evidence_refs)))]
        def priority(page):
            identity = page['evidence_ref']
            receipt = private.evidence_progress.get(identity)
            complete = receipt is not None and receipt.fully_inspected()
            pending = (private.evidence_refs and identity == private.evidence_refs[-1] and receipt is not None
                       and receipt.processed and (page['offset'], page['end_offset']) not in receipt.delivered)
            return (not pending, not (page['offset'] > 0 and not complete), identity not in work.evidence_refs,
                    complete, page.get('source_file') is None)
        pages.sort(key=priority)  # Stable ties preserve most-recent-first ordering.
        records, used, omitted = [], 0, 0
        for record in pages:
            size = len(_json(record).encode("utf-8"))
            if used + size > self.CONTEXT_BYTES:
                omitted += 1
                continue
            records.append(record)
            used += size
        return {"snapshot_id": self.snapshot_id, "scope": work.files,
                "evidence": records, "omitted_evidence_count": omitted,
                "limitations": ["Context is selective; retrieve omitted evidence by reference/offset"] if omitted else []}

    def validate_confirmation(self, candidate, decision, work, private):
        claim = FindingCandidate.model_validate({**candidate, "evidence_refs": decision.evidence_refs})
        StructuralEvidenceGate(self).validate(claim, work)
        location = claim.location
        if not any(private.evidence_progress[ref].fully_inspected()
                   and (record := self.scoped_evidence(ref, work)).get("file_path") == location.file_path
                   and record.get("start_line", 0) <= location.start_line
                   and record.get("end_line", 0) >= location.end_line
                   for ref in decision.evidence_refs):
            raise ValueError("confirmation lacks fully inspected source evidence covering the claim")

    def validate_candidate(self, candidate, work, private):
        StructuralEvidenceGate(self).validate(candidate, work)
        location = candidate.location
        if not any((receipt := private.evidence_progress.get(ref)) is not None and receipt.fully_inspected()
                   and (record := self.scoped_evidence(ref, work)).get("tool") == "read_source"
                   and record.get("file_path") == location.file_path
                   and record.get("start_line", 0) <= location.start_line
                   and record.get("end_line", 0) >= location.end_line for ref in candidate.evidence_refs):
            raise ValueError("candidate lacks acknowledged source covering its location")

    def tools(self, command_runtime=None, database_runtime=None) -> PermissionedTools:
        tools = PermissionedTools()
        tools.validate_confirmation = self.validate_confirmation
        tools.validate_candidate = self.validate_candidate
        async def read_source(arguments, work):
            return self._read_sources(arguments, work)
        async def read_evidence(arguments, work):
            identity = arguments["evidence_ref"]
            offset = arguments.get("offset", 0)
            self.evidence_page(identity, work, offset=offset, max_chars=arguments.get("max_chars", 1500))
            return ToolObservation(evidence_ref=identity, offset=offset, max_chars=arguments.get("max_chars", 1500))
        async def facts(name, arguments, work):
            allowed = {"file_path", "symbol"} if name == "symbol_lookup" else {"file_path"}
            if set(arguments) - allowed or "file_path" not in arguments:
                raise ValueError("analysis requires exactly file_path")
            path = self._scoped_path(arguments["file_path"], work)
            data = self.analyze()[path]
            if data["status"] != "parsed":
                raise ToolFailure("parser_unavailable", "Use read_source or code_search; parser facts are unavailable for this source.")
            scope = [path]
            if name in {"dependency_graph", "import_graph"}:
                data = import_edges(self.analyze(), work.files)
                data["edges"] = [edge for edge in data["edges"] if edge["from"] == path]
                data["unresolved"] = [edge for edge in data["unresolved"] if edge["from"] == path]
                scope = sorted({path} | {edge["to"] for edge in data["edges"]})
            elif name == "call_graph":
                data = {"calls": data["calls"], "limitations": data["limitations"]}
            elif name == "symbol_lookup":
                symbol = arguments.get("symbol")
                if symbol is not None and (not isinstance(symbol, str) or not 1 <= len(symbol) <= 256):
                    raise ValueError("bounded symbol name required")
                data = [item for item in data["symbols"] if symbol is None or item["name"] == symbol]
            elif name == "complexity":
                data = {"cyclomatic_lower_bound": 1 + data["branch_count"], "symbol_count": len(data["symbols"]),
                        "limitations": ["Syntactic complexity estimate, not a maintainability verdict"]}
            return self._record({"tool": name, "file_path": path, "source_scope": scope, "inspected": scope, "start_line": 1,
                                 "end_line": self.manifest.entries[path].line_count,
                                 "content_hash": self.manifest.entries[path].content_hash, "data": data}, work=work)
        async def config(arguments, work):
            if set(arguments) != {"file_path"}:
                raise ValueError("config_read requires exactly file_path")
            path = self._scoped_path(arguments["file_path"], work)
            source = self._source(path)
            try:
                data = json.loads(source) if path.endswith(".json") else tomllib.loads(source) if path.endswith(".toml") else None
            except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
                details = {key: value for key, value in {"line": getattr(exc, "lineno", None),
                           "column": getattr(exc, "colno", None)}.items() if type(value) is int}
                raise ToolFailure("invalid_configuration", "Check captured JSON/TOML syntax; use read_source to inspect the reported location.",
                                  details=details) from exc
            if data is None:
                raise LookupError("Only captured JSON/TOML configuration is supported")
            def redact(value):
                if isinstance(value, dict):
                    return {key: "[redacted]" if re.search(r"secret|password|token|api.?key|credential|private.?key", key, re.I)
                            else redact(item) for key, item in value.items()}
                return [redact(item) for item in value] if isinstance(value, list) else value
            return self._record({"tool": "config_read", "file_path": path, "data": redact(data)}, work=work)
        async def git(name, arguments, work):
            if set(arguments) != {"file_path"}:
                raise ValueError("Git tools require exactly file_path")
            path = self._scoped_path(arguments["file_path"], work)
            metadata = self.manifest.git_metadata
            value = metadata.diffs.get(path) if name == "git_diff" else metadata.history.get(path)
            if value is None:
                raise LookupError("No immutable Git metadata captured for this source")
            return self._record({"tool": name, "file_path": path, "data": value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
                "limitations": ["Git metadata is client-reported context, not causal verification", *metadata.limitations]}, work=work)
        async def repo_map(arguments, work):
            if arguments:
                raise ValueError("repository map takes no arguments")
            return self._record({"tool": "repo_map", "source_scope": list(work.files), "data": {path: entry.model_dump(mode="json")
                                for path, entry in self.manifest.entries.items() if path in work.files}}, work=work)
        async def search(arguments, work):
            if set(arguments) - {"query", "file_path"} or not isinstance(arguments.get("query"), str) or not 1 <= len(arguments["query"]) <= 256:
                raise ValueError("bounded literal query required")
            paths = [self._scoped_path(arguments["file_path"], work)] if arguments.get("file_path") is not None else work.files
            matches, scanned = [], []
            for path in paths:
                source = self._source(path)
                scanned.append(path)
                for line, text in enumerate(source.splitlines(), 1):
                    if arguments["query"] in text:
                        matches.append({"file_path": path, "line": line, "text": text[:500]})
                        if len(matches) >= 20:
                            break
                if len(matches) >= 20:
                    break
            return self._record({"tool": "code_search", "data": matches, "source_scope": scanned, "inspected": scanned,
                                 "limitations": ["Search result is bounded to 20 matches"]}, work=work)
        tools.register("read_source", read_source)
        tools.register("read_evidence", read_evidence)
        tools.register("repo_map", repo_map)
        tools.register("code_search", search)
        tools.register("config_read", config)
        tools.register("git_diff", partial(git, "git_diff"))
        tools.register("git_history", partial(git, "git_history"))
        for name in ("parse_ast", "symbol_lookup", "call_graph", "dependency_graph", "import_graph", "complexity"):
            tools.register(name, partial(facts, name))
        if command_runtime is not None:
            from devwatch.review.tool_runtime import COMMAND_TOOLS
            async def command(name, arguments, work):
                from devwatch.review.contracts import AgentAction
                return await command_runtime.execute(work, AgentAction(kind="call_tool", tool=name, arguments=arguments))
            def command_available(name, work):
                return any(definition.tool == name and set(definition.files).issubset(work.files)
                           for definition in command_runtime.commands.values())
            for name in COMMAND_TOOLS:
                if database_runtime is None or name not in {"db_analyze", "query_analyze"}:
                    tools.register(name, partial(command, name), available=partial(command_available, name))
            tools.register("write_artifact", command_runtime.write_measurement, available=command_runtime.grants_measurement)
        if database_runtime is not None:
            from devwatch.review.tool_catalogue import DatabaseArguments, QueryArguments
            async def database(name, arguments, work):
                from devwatch.review.contracts import AgentAction
                return await database_runtime.execute(work, AgentAction(kind="call_tool", tool=name, arguments=arguments))
            def database_available(work):
                return any(database_runtime.job.owner in policy.owners for policy in database_runtime.policies.values())
            for name in ("db_analyze", "query_analyze"):
                tools.register(name, partial(database, name), available=database_available,
                               arguments_model=DatabaseArguments if name == "db_analyze" else QueryArguments)
        return tools


class StructuralEvidenceGate:
    def __init__(self, repository: RepositoryContext):
        self.repository = repository

    def validate(self, candidate: FindingCandidate, task: ReviewTask) -> None:
        candidate = FindingCandidate.model_validate(candidate.model_dump())
        repo, location = self.repository, candidate.location
        entry = repo.manifest.entries.get(location.file_path)
        if (location.snapshot_id != repo.snapshot_id or location.file_path not in task.files
                or entry is None or location.end_line > entry.line_count):
            raise ValueError("candidate location is outside the immutable assigned source")
        records = [repo.scoped_evidence(identity, task) for identity in candidate.evidence_refs]
        if not any(record.get("file_path") == location.file_path
                   and record.get("content_hash") == entry.content_hash
                   and record.get("start_line", 0) <= location.start_line
                   and record.get("end_line", 0) >= location.end_line for record in records):
            raise ValueError("candidate lacks source evidence covering its location")


class SharedBlackboard:
    """Only validated result reducers publish shared data; private state stays private."""
    def __init__(self, gate: StructuralEvidenceGate, *, runtime_limitations: tuple[str, ...] = ()):
        self.gate = gate
        self.runtime_limitations = runtime_limitations
        self.candidates: dict[str, FindingCandidate] = {}
        self.candidate_tasks: dict[str, str] = {}
        self.results: dict[str, SpecialistResult] = {}
        self.quarantined: dict[str, list[CandidateRejection]] = {}

    def publish(self, task: ReviewTask, result: SpecialistResult) -> None:
        result = SpecialistResult.model_validate(result.model_dump())
        if result.task_id != task.task_id or result.agent_id != task.agent_id:
            raise ValueError("result does not belong to this review task")
        admitted = []
        for index, candidate in enumerate(result.candidates):
            try:
                self.gate.validate(candidate, task)
            except (ValueError, FileNotFoundError, PermissionError) as exc:
                result.quarantined.append(CandidateRejection(index=index, title=candidate.title[:200], reason=str(exc)[:1000]))
                continue
            claim = candidate.model_dump(mode="json", exclude={"evidence_refs", "confidence", "remediation"})
            identity = "finding-" + sha256(_json({"task_id": task.task_id, "claim": claim}).encode()).hexdigest()[:24]
            previous = self.candidates.get(identity)
            if previous is None and len(self.candidates) >= Config.MAX_CANDIDATE_FINDINGS:
                result.quarantined.append(CandidateRejection(index=index, title=candidate.title[:200], reason="candidate capacity exceeded"))
                continue
            if previous is not None:
                merged = list(dict.fromkeys(previous.evidence_refs + candidate.evidence_refs))
                candidate.evidence_refs = merged[:8]
                if len(merged) > 8:
                    result.coverage.limitations.append("Additional evidence remains in task artifacts; candidate reference limit reached.")
                candidate.confidence = min(previous.confidence, candidate.confidence)
            self.candidates[identity] = candidate.model_copy(deep=True)
            self.candidate_tasks[identity] = task.task_id
            admitted.append(candidate)
        result.candidates = admitted
        if result.quarantined:
            result.coverage.failed[task.task_id] = "invalid_evidence"
            result.coverage.limitations.append(f"{len(result.quarantined)} candidate(s) quarantined for task {task.task_id}; valid siblings retained.")
        previous_rejections = self.quarantined.get(task.task_id, [])
        self.quarantined[task.task_id] = previous_rejections + [item for item in result.quarantined if item not in previous_rejections]
        previous_result = self.results.get(task.task_id)
        if previous_result is not None:
            result.coverage.failed = {**previous_result.coverage.failed, **result.coverage.failed}
            result.coverage.skipped = {**previous_result.coverage.skipped, **result.coverage.skipped}
            result.coverage.inspected_files = sorted(set(previous_result.coverage.inspected_files + result.coverage.inspected_files))
            result.coverage.limitations = sorted(set(previous_result.coverage.limitations + result.coverage.limitations))
        self.results[task.task_id] = result.model_copy(deep=True)

    def provenance(self):
        return {identity: {'task_id': task_id, 'agent_id': self.results[task_id].agent_id.value}
                for identity, task_id in self.candidate_tasks.items()}

    def coverage(self) -> Coverage:
        capture = self.gate.repository.manifest.capture_coverage
        output = Coverage(skipped=dict(capture.skipped), failed=dict(capture.failed),
                          limitations=list(capture.limitations) + list(self.runtime_limitations))
        if capture.skipped or capture.failed or capture.limitations:
            output.limitations.append("Capture omissions are client-reported; inspection coverage covers captured source only.")
        for identity, result in sorted(self.results.items()):
            output.inspected_files.extend(result.coverage.inspected_files)
            output.inspected_symbols.extend(result.coverage.inspected_symbols)
            output.failed.update(result.coverage.failed)
            output.skipped.update(result.coverage.skipped)
            output.limitations.extend(result.coverage.limitations)
        output.inspected_files = sorted(set(output.inspected_files))
        output.inspected_symbols = sorted(set(output.inspected_symbols))
        output.limitations = sorted(set(output.limitations))
        for path in self.gate.repository.manifest.entries:
            if path not in output.inspected_files:
                output.skipped.setdefault(path, "not_inspected")
        return output
