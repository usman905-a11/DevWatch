"""Argument contracts shared by model-facing catalogues and runtime admission."""

from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from devwatch.review.contracts import ContractModel, SourceLocation
from devwatch.review.prompts import response_schema


class Arguments(ContractModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FileArguments(Arguments):
    file_path: str = Field(min_length=1, description="Captured repository-relative path in the assigned files")

    @field_validator("file_path")
    @classmethod
    def relative_path(cls, value):
        return SourceLocation.relative_source_path(value)


class SourceArguments(FileArguments):
    additional_files: list[str] = Field(default_factory=list, max_length=3,
        description="Up to 3 other assigned paths; same range, separate paged refs.")

    @field_validator('additional_files')
    @classmethod
    def relative_additional_paths(cls, values):
        return [SourceLocation.relative_source_path(value) for value in values]

    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1, description="Inclusive; <=200 lines; EOF clamps. Omit/null selects 80. Paged results.")

    @model_validator(mode="after")
    def bounded_range(self):
        paths = [self.file_path, *self.additional_files]
        if len(paths) != len(set(paths)):
            raise ValueError('source batch paths must be unique')
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


TOOL_ARGUMENTS: dict[str, type[Arguments]] = {
    "read_source": SourceArguments, "read_evidence": EvidenceArguments,
    "repo_map": Arguments, "code_search": SearchArguments, "symbol_lookup": SymbolArguments,
    **{name: FileArguments for name in ("parse_ast", "call_graph", "dependency_graph", "import_graph", "complexity", "config_read", "git_diff", "git_history")},
}
DESCRIPTIONS = {
    "read_source": "Read immutable source lines (1-based, <=200). EOF clamps; empty accepts start=1.",
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
}


def describe_tool(name: str, model: type[Arguments]) -> dict[str, Any]:
    description = DESCRIPTIONS[name]
    return {"name": name, "description": description,
        "arguments": response_schema(model),
        "output": "Evidence reference (processed), retrievable via read_evidence/context pages. Processing does not imply delivery or inspection."}
