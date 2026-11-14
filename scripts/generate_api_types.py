"""Generate TypeScript API types from DevWatch's FastAPI OpenAPI & Pydantic schemas."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, get_args

from devwatch.review.contracts import ModelTier, ReportDraft
from devwatch.review.jobs import JobStatus, StepRenderInfo, StepStatus, StepType, StepUpdatePayload
from devwatch.review.service import ServiceSettings, create_app


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "frontend" / "src" / "review" / "api-types.ts"


def _collect_schemas() -> dict[str, Any]:
    app = create_app(
        settings=ServiceSettings(
            runtime_root=ROOT / ".devwatch" / "openapi-tmp",
            models={tier: "gpt-4o-mini" for tier in ModelTier},
        )
    )
    openapi = app.openapi()
    schemas = dict(openapi.get("components", {}).get("schemas", {}))
    for model in (ReportDraft, StepRenderInfo, StepUpdatePayload):
        dumped = model.model_json_schema(ref_template="#/components/schemas/{model}")
        defs = dumped.pop("$defs", {})
        for name, sub in defs.items():
            schemas.setdefault(name, sub)
        schemas[model.__name__] = dumped
    for name, literal_type in (("JobStatus", JobStatus), ("StepType", StepType), ("StepStatus", StepStatus)):
        schemas[name] = {"type": "string", "enum": list(get_args(literal_type))}
    return schemas


def _allows_null(prop: Any) -> bool:
    if not isinstance(prop, dict):
        return False
    if prop.get("type") == "null":
        return True
    for key in ("anyOf", "oneOf"):
        if key in prop and any(isinstance(item, dict) and item.get("type") == "null" for item in prop[key]):
            return True
    return False


def _ts_type(node: dict[str, Any], indent: int = 0) -> str:
    if not isinstance(node, dict):
        return "unknown"
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]
    if "const" in node:
        return repr(node["const"]).replace("'", "\"") if isinstance(node["const"], str) else str(node["const"]).lower()
    if "enum" in node:
        parts = [f"'{v}'" if isinstance(v, str) else ("null" if v is None else str(v).lower() if isinstance(v, bool) else str(v)) for v in node["enum"]]
        return " | ".join(parts)
    for key in ("anyOf", "oneOf"):
        if key in node:
            choices = [_ts_type(item, indent) for item in node[key]]
            deduped = list(dict.fromkeys(choices))
            return " | ".join(deduped)
    if "allOf" in node:
        return " & ".join(_ts_type(item, indent) for item in node["allOf"])

    schema_type = node.get("type")
    if schema_type == "null":
        return "null"
    if schema_type == "boolean":
        return "boolean"
    if schema_type in ("integer", "number"):
        return "number"
    if schema_type == "string":
        return "string"
    if schema_type == "array":
        items = node.get("items")
        prefix = node.get("prefixItems")
        if isinstance(prefix, list):
            return "[" + ", ".join(_ts_type(item, indent) for item in prefix) + "]"
        inner = _ts_type(items, indent) if isinstance(items, dict) else "unknown"
        return f"({inner})[]" if " | " in inner else f"{inner}[]"
    if schema_type == "object" or "properties" in node or "additionalProperties" in node:
        props = node.get("properties")
        additional = node.get("additionalProperties")
        required = set(node.get("required", ()))
        if not props:
            if isinstance(additional, dict):
                return f"Record<string, {_ts_type(additional, indent)}>"
            return "Record<string, unknown>"
        pad = "  " * (indent + 1)
        close_pad = "  " * indent
        lines = ["{"]
        for name, prop in props.items():
            # Non-nullable defaulted fields (e.g. Field(default_factory=list/dict)) are always present in serialized JSON.
            is_required = name in required or (isinstance(prop, dict) and not _allows_null(prop))
            opt = "" if is_required else "?"
            lines.append(f"{pad}{name}{opt}: {_ts_type(prop, indent + 1)}")
        lines.append(f"{close_pad}}}")
        return "\n".join(lines)
    return "unknown"


def render_typescript() -> str:
    schemas = _collect_schemas()
    chunks = [
        "/* eslint-disable */",
        "// Auto-generated from FastAPI OpenAPI / Pydantic schemas by scripts/generate_api_types.py",
        "",
    ]
    for name in sorted(schemas):
        schema = schemas[name]
        if schema.get("type") == "object" or "properties" in schema:
            body = _ts_type(schema, 0)
            if body.startswith("{"):
                chunks.append(f"export interface {name} {body}\n")
                continue
        chunks.append(f"export type {name} = {_ts_type(schema, 0)}\n")
    return "\n".join(chunks).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit non-zero if api-types.ts is out of date.")
    args = parser.parse_args()
    content = render_typescript()
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != content:
            print(f"{OUTPUT_PATH} is out of date. Run python scripts/generate_api_types.py.")
            return 1
        return 0
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
