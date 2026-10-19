"""Controlled tool failures; never expose dependency exception text as feedback."""

from hashlib import sha256
import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError


HINTS = {
    "invalid_source_range": "Choose start_line within line_count and request at most max_lines. Omit end_line for a default page; empty files accept start_line=1.",
    "invalid_evidence_offset": "Use an offset below total_chars; follow next_offset from a delivered page.",
    "evidence_not_found": "Use an evidence_ref returned by a tool in this snapshot.",
    "invalid_arguments": "Correct the listed fields using the advertised argument schema; unknown fields are not permitted.",
    "tool_unavailable": "This tool/data is unavailable. Choose another permitted tool or report the limitation.",
    "parser_unavailable": "Use read_source or code_search. Parser facts are unavailable for this source; do not infer an AST from text.",
    "invalid_configuration": "Check captured JSON/TOML syntax; use read_source to inspect the reported location.",
    "invalid_query": "Check SELECT syntax and parameter bindings against owner-granted schema; use db_analyze. No query values are returned in this diagnostic.",
    "database_unavailable": "Read-only database inspection failed. Use other permitted evidence or report the limitation.",
    "tool_read_failure": "The read failed without evidence. Correct the request or report the limitation; do not repeat identical arguments.",
    "evidence_integrity_failure": "Stop: evidence integrity could not be verified.",
    "snapshot_integrity_failure": "Stop: captured source integrity could not be verified.",
    "permission_denied": "Stop: the requested tool, source or capability is outside the granted scope.",
    "tool_timeout": "Stop: the tool timed out; completion may be unknown. Do not replay it.",
    "unknown_tool_completion": "Stop: completion is unknown. Do not replay the operation.",
    "tool_execution_failed": "Stop: tool execution failed; effects cannot be assumed absent.",
    "repeated_tool_failure": "Stop: these arguments already failed. The duplicate was blocked before execution.",
}


class ToolDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: str = Field(max_length=64)
    code: str = Field(max_length=64)
    hint: str = Field(max_length=256)
    recoverable: bool
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments: dict = Field(default_factory=dict, max_length=16)
    details: dict = Field(default_factory=dict, max_length=8)
    redacted_fields: int = Field(default=0, ge=0)


def safe_arguments(arguments, files):
    """Retain useful coordinates/owned paths; never retain arbitrary query/value text."""
    safe, redacted = {}, 0
    for key, value in arguments.items():
        if key == "file_path" and isinstance(value, str) and value in files and len(value) <= 256:
            safe[key] = value
        elif key in {"start_line", "end_line", "offset", "max_chars"} and (
                value is None or type(value) in {int, bool} and abs(value) <= 2**31):
            safe[key] = value
        elif key == "evidence_ref" and isinstance(value, str) and re.fullmatch(r"evidence-[0-9a-f]{64}", value):
            safe[key] = value
        else:
            redacted += 1
            if key in {"file_path", "start_line", "end_line", "offset", "max_chars", "query", "parameters", "symbol", "command_id", "database_id"}:
                safe[key] = "[redacted]"
    return safe, redacted


def failure_identity(tool, arguments, model):
    try:
        arguments = model.model_validate(arguments).model_dump(mode="json")
    except (ValueError, AttributeError):
        pass
    # Non-finite invalid inputs must still have a stable identity before validation.
    encoded = json.dumps([tool, arguments], sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def diagnose(tool, arguments, files, error, fingerprint, *, replay_safe=True):
    details = {}
    if isinstance(error, ToolFailure):
        code, recoverable = error.code, error.recoverable
        details = {key: value for key, value in error.details.items()
                   if key in {"line_count", "max_lines", "total_chars", "line", "column"} and type(value) is int and value >= 0}
    elif isinstance(error, ValidationError):
        code, recoverable = "invalid_arguments", True
        fields = {"file_path", "start_line", "end_line", "offset", "max_chars", "evidence_ref", "query", "parameters", "symbol", "command_id", "database_id"}
        details = {"fields": sorted({str(item["loc"][0]) if item["loc"] and item["loc"][0] in fields else "unrecognized_field"
                                     for item in error.errors()})[:8]}
    else:
        code = ("permission_denied" if isinstance(error, PermissionError) else
                "tool_timeout" if isinstance(error, TimeoutError) else
                "tool_read_failure" if isinstance(error, (LookupError, ValueError, FileNotFoundError)) and replay_safe else
                "tool_execution_failed")
        recoverable = code == "tool_read_failure"
    if code not in HINTS:
        code, recoverable, details = "tool_execution_failed", False, {}
    safe, redacted = safe_arguments(arguments, files)
    return ToolDiagnostic(tool=tool, code=code, hint=HINTS[code], recoverable=recoverable,
                          fingerprint=fingerprint, arguments=safe, details=details, redacted_fields=redacted)


class ToolFailure(ValueError):
    def __init__(self, code: str, hint: str, *, recoverable: bool = True, details=None, arguments=None):
        self.code = code
        self.hint = hint
        self.recoverable = recoverable
        self.details = dict(details or {})
        self.arguments = dict(arguments or {})
        super().__init__(hint)
