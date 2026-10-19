"""Argument contracts shared by model-facing catalogues and runtime admission."""

from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from devwatch.review.contracts import ContractModel, SourceLocation


class Arguments(ContractModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FileArguments(Arguments):
    file_path: str = Field(min_length=1, description="Captured repository-relative path in the assigned files")

    @field_validator("file_path")
    @classmethod
    def relative_path(cls, value):
        return SourceLocation.relative_source_path(value)


class SourceArguments(FileArguments):
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1, description="Inclusive; at most 200 lines; clamped at EOF. Start must exist. Null/omitted selects up to 80. Large results are paged.")

    @model_validator(mode="after")
    def bounded_range(self):
        if self.end_line is not None and not self.start_line <= self.end_line < self.start_line + 200:
            raise ValueError("invalid or unbounded source range")
        return self


class EvidenceArguments(Arguments):
    evidence_ref: str = Field(pattern=r"^evidence-[0-9a-f]{64}$")
    offset: int = Field(default=0, ge=0, description="Character offset in canonical evidence JSON")
    max_chars: int = Field(default=1500, ge=1, le=3000)


class SymbolArguments(FileArguments):
    symbol: str | None = Field(default=None, min_length=1, max_length=256)


class SearchArguments(Arguments):
    query: str = Field(min_length=1, max_length=256, description="Literal search; at most 20 matches")
    file_path: str | None = Field(default=None, min_length=1)

    @field_validator("file_path")
    @classmethod
    def relative_path(cls, value):
        return SourceLocation.relative_source_path(value) if value is not None else None


class CommandArguments(Arguments):
    command_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", description="Runtime-approved command for this tool/task")


class ArtifactArguments(Arguments):
    evidence_ref: str = Field(pattern=r"^evidence-[0-9a-f]{64}$", description="Approved profiling/benchmark measurement evidence")


class DatabaseArguments(Arguments):
    database_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", description="Owner-granted database ID")


class QueryArguments(DatabaseArguments):
    query: str = Field(min_length=1, max_length=8192, pattern=r"(?is)^\s*select\b.*", description="SELECT only; query plan, no execution")
    parameters: list[str | int | float | None] = Field(default_factory=list, max_length=30)


TOOL_ARGUMENTS: dict[str, type[Arguments]] = {
    "read_source": SourceArguments, "read_evidence": EvidenceArguments,
    "repo_map": Arguments, "code_search": SearchArguments, "symbol_lookup": SymbolArguments,
    "write_artifact": ArtifactArguments,
    **{name: FileArguments for name in ("parse_ast", "call_graph", "dependency_graph", "import_graph", "complexity", "config_read", "git_diff", "git_history")},
    **{name: CommandArguments for name in ("run_tests", "run_command", "lint", "type_check", "coverage", "sast", "profile", "benchmark", "db_analyze", "query_analyze")},
}
DESCRIPTIONS = {
    "read_source": "Read 1-based inclusive immutable source lines, at most 200. End clamps to EOF; start must exist (empty files accept 1).",
    "read_evidence": "Page scoped evidence JSON by character offset; follow next_offset. Acknowledge delivered pages with inspected_evidence.",
    "repo_map": "List captured file metadata in the assigned scope.",
    "code_search": "Search assigned immutable files for a literal string; at most 20 matches, each truncated to 500 characters.",
    "parse_ast": "Retrieve deterministic parser facts for an assigned file; unsupported or invalid syntax requires source/search fallback.",
    "symbol_lookup": "List parsed symbols in an assigned file, optionally matching an exact symbol name; no runtime resolution.",
    "call_graph": "Retrieve syntactic call sites in an assigned file; targets are not proven runtime dispatch.",
    "dependency_graph": "Retrieve resolved local import edges from an assigned file within task scope, plus unresolved imports.",
    "import_graph": "Retrieve resolved local import edges from an assigned file within task scope, plus unresolved imports.",
    "complexity": "Estimate syntactic cyclomatic lower bound and symbol count; not a maintainability verdict.",
    "config_read": "Read captured JSON/TOML configuration with sensitive keys redacted.",
    "git_diff": "Read captured client-reported Git diff; not causal verification.",
    "git_history": "Read captured client-reported Git history; not causal verification.",
    "run_tests": "Run the exact approved test command in assigned scratch files; inspect bounded output and exit status.",
    "run_command": "Run an exact approved host command in assigned scratch files; no model-supplied shell or argv.",
    "lint": "Run the exact approved lint command in assigned scratch files; findings depend on configured rules.",
    "type_check": "Run the exact approved type-check command in assigned scratch files; inspect output and exit status.",
    "coverage": "Run the exact approved coverage command in assigned scratch files; output is limited to the configured tests.",
    "sast": "Run the exact approved static security command in assigned scratch files; reported matches require review.",
    "profile": "Run the exact approved profiling command in assigned scratch files; results describe that configured workload.",
    "benchmark": "Run the exact approved benchmark command in assigned scratch files; results describe that configured workload.",
    "db_analyze": "Run the exact approved database-analysis command in assigned scratch files; inspect bounded output and exit status.",
    "query_analyze": "Run the exact approved query-analysis command in assigned scratch files; inspect bounded output and exit status.",
    "write_artifact": "Serialize an explicitly granted measurement to a runtime-owned destination.",
}


def describe_tool(name: str, model: type[Arguments]) -> dict[str, Any]:
    description = ("Inspect read-only owner-granted SQLite table/column metadata; no application rows."
                   if model is DatabaseArguments else
                   "Explain a SELECT plan against an owner-granted SQLite database; no query execution or result rows."
                   if model is QueryArguments else DESCRIPTIONS[name])
    return {"name": name, "description": description,
        "arguments": model.model_json_schema(),
        "output": "Evidence reference (processed), retrievable via read_evidence/context pages. Processing does not imply delivery or inspection."}
