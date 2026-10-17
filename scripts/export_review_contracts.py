"""Export canonical transport validation schemas; --check detects consumer drift."""
import argparse
import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from devwatch.review.contracts import ReportDraft
from devwatch.review.jobs import JobView, PersistedEvent
from devwatch.review.stores import SnapshotManifest


def export() -> str:
    _, schema = models_json_schema([(model, "validation") for model in
        (JobView, PersistedEvent, SnapshotManifest, ReportDraft)])
    # Responses serialize every field, including defaults/nulls. Requiring them
    # prevents optional input defaults becoming undefined browser state.
    for name, definition in schema["$defs"].items():
        if "properties" in definition:
            # New event metadata is additive: older persisted/replayed payloads
            # remain readable by upgraded consumers. Keep the original wire keys.
            definition["required"] = (sorted({"status", "agent_id", "task_id", "tool", "evidence_ref",
                "error_code", "duration_seconds", "total_tokens"}) if name == "EventPayload"
                else sorted(definition["properties"]))
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "frontend/src/review/wire-schema.json"
    encoded = export()
    if args.check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != encoded:
            raise SystemExit("Browser wire schema differs from canonical backend contracts; regenerate it.")
    else:
        destination.write_text(encoded, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
