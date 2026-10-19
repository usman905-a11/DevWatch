"""Argument contracts shared by model-facing catalogues and runtime admission."""

from typing import Any

from pydantic import ConfigDict, Field, model_validator

from devwatch.review.contracts import ContractModel, SourceLocation


class Arguments(ContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FileArguments(Arguments):
    file_path: str = Field(min_length=1, description="Captured repository-relative path in the assigned files")


class SourceArguments(FileArguments):
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1, description="Inclusive; at most 200 lines; clamped at EOF. Start must exist. Null/omitted selects up to 80. Large results are paged.")

    @model_validator(mode="after")
    def bounded_range(self):
        SourceLocation.relative_source_path(self.file_path)
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
    "read_source": "Read a bounded inclusive immutable source range.",
    "read_evidence": "Retrieve a scoped page of stored evidence; use next_offset for subsequent pages.",
    "repo_map": "List captured file metadata in the assigned scope.",
    "code_search": "Search assigned immutable files for a literal string.",
    "config_read": "Read captured JSON/TOML configuration with sensitive keys redacted.",
    "git_diff": "Read captured client-reported Git diff; not causal verification.",
    "git_history": "Read captured client-reported Git history; not causal verification.",
    "write_artifact": "Serialize an explicitly granted measurement to a runtime-owned destination.",
}


def describe_tool(name: str, model: type[Arguments]) -> dict[str, Any]:
    return {"name": name, "description": DESCRIPTIONS.get(name, (
        "Inspect read-only owner-granted database metadata/query plans." if model in {DatabaseArguments, QueryArguments}
        else "Execute the exact runtime-approved command in assigned scratch files." if model is CommandArguments
        else "Retrieve deterministic scoped parser facts; parser failures are reported explicitly.")),
        "arguments": model.model_json_schema(),
        "output": "Evidence reference (processed), retrievable via read_evidence/context pages. Processing does not imply delivery or inspection."}
