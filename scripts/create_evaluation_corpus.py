"""Materialize the versioned, independently labelled contract-probe corpus.

Each family has explicit defective/correct source and three input/expected pairs.
Labels are never passed to the reviewer. Probes express public behavior contracts.
This is an offline integration corpus, not a live-model accuracy benchmark.
"""
import json
from pathlib import Path

FAMILIES = [
    ("first_default", "python", "return items[0]", "return items[0] if items else None", [("[]", "None"), ("()", "None"), ("''", "None")], "items", "Empty input returns None"),
    ("sum_values", "python", "return sum(items) + 1", "return sum(items)", [("[2, 3]", "5"), ("[-4, 2]", "-2"), ("[]", "0")], "items", "Return the mathematical sum"),
    ("absolute", "python", "return value", "return abs(value)", [("-1", "1"), ("-17", "17"), ("-0.5", "0.5")], "value", "Absolute value is nonnegative"),
    ("inclusive_end", "python", "return list(range(end))", "return list(range(end + 1))", [("0", "[0]"), ("2", "[0, 1, 2]"), ("4", "[0, 1, 2, 3, 4]")], "end", "Include the upper endpoint"),
    ("division", "python", "return value // 2", "return value / 2", [("3", "1.5"), ("7", "3.5"), ("-3", "-1.5")], "value", "Return half without truncation"),
    ("preserve_input", "python", "items.sort(); return items", "return sorted(items)", [("[3, 1, 2]", "[1, 2, 3]"), ("[2, 1]", "[1, 2]"), ("[0, -2]", "[-2, 0]")], "items", "Sort without mutating input"),
    ("deduplicate", "python", "return sorted(set(items))", "return list(dict.fromkeys(items))", [("[3, 1, 3]", "[3, 1]"), ("[8, 2, 8]", "[8, 2]"), ("[4, 0, 4]", "[4, 0]")], "items", "Deduplicate preserving first occurrence order"),
    ("clamp", "javascript", "return Math.max(0, value);", "return Math.min(10, Math.max(0, value));", [("11", "10"), ("100", "10"), ("10.5", "10")], "value", "Clamp into the closed interval zero to ten"),
    ("discount", "javascript", "return price * (1 - 10);", "return price * 0.9;", [("100", "90"), ("200", "180"), ("50", "45")], "price", "Apply a ten percent discount"),
    ("page_offset", "javascript", "return page * 10;", "return (page - 1) * 10;", [("1", "0"), ("2", "10"), ("4", "30")], "page", "One-based page numbers map to zero-based offsets"),
]


def main():
    cases = []
    for family, language, defective, correct, examples, argument, contract in FAMILIES:
        for index, (input_value, expected) in enumerate(examples, 1):
            for broken, body in ((True, defective), (False, correct)):
                if language == "python":
                    path, probe_path = "subject.py", "probe.py"
                    source = f"def f({argument}):\n    {body}\n"
                    probe = ("import importlib.util\nfrom pathlib import Path\n"
                        "spec=importlib.util.spec_from_file_location('subject', Path(__file__).with_name('subject.py'))\n"
                        "module=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n"
                        f"value={input_value}\nbefore=repr(value)\nresult=module.f(value)\nassert result == {expected}, 'Contract result mismatch'\n")
                    if family == "preserve_input":
                        probe += "assert repr(value) == before, 'Contract forbids input mutation'\n"
                else:
                    path, probe_path = "subject.js", "probe.js"
                    source = f"function f({argument}) {{\n  {body}\n}}\nmodule.exports = {{f}};\n"
                    probe = f"const assert=require('node:assert/strict');\nconst {{f}}=require('./subject.js');\nassert.deepEqual(f({input_value}), {expected});\n"
                cases.append({"case_id": f"{family}-{index}-{'defect' if broken else 'clean'}", "family": family,
                    "language": language, "contract": contract, "files": {path: source, probe_path: probe},
                    "subject": path, "probe": probe_path, "expected_defect": broken})
    destination = Path(__file__).resolve().parents[1] / "tests/fixtures/canonical-review-eval-v2.json"
    destination.write_text(json.dumps({"version": "canonical-review-eval-v2", "method": "independent labels and executable contract probes",
        "not_measured": "live-model reasoning accuracy", "cases": cases}, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(cases)} labelled cases in {len(FAMILIES)} behavior families")


if __name__ == "__main__":
    main()
