import os
import json
import pytest
from typing import List, Dict, Any
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.tools import redact_secret_in_snippet
from devwatch.scanner import CodebaseScanner


BENCHMARK_SAMPLES = [
    {
        "name": "sqli_sample",
        "file_path": "db/queries.py",
        "code": """def get_user(db, username):
    # SQL Injection flaw
    query = f"SELECT * FROM users WHERE username='{username}'"
    return db.execute(query)
""",
        "expected_categories": ["Security"],
        "expected_keywords": ["sql"],
    },
    {
        "name": "cmd_inject_sample",
        "file_path": "utils/network.py",
        "code": """import os

def ping_host(host_ip):
    # OS Command Injection flaw
    os.system("ping -c 1 " + host_ip)
""",
        "expected_categories": ["Security"],
        "expected_keywords": ["command", "os.system", "shell"],
    },
    {
        "name": "secret_leak_sample",
        "file_path": "config/settings.py",
        "code": """# Production settings
AWS_SECRET_ACCESS_KEY = "AKIA1234567890ABCDEF1234"
API_KEY = "sk-live-99887766554433221100"
""",
        "expected_categories": ["Security"],
        "expected_keywords": ["secret", "credential", "api_key"],
    },
    {
        "name": "eval_exec_sample",
        "file_path": "services/calc.py",
        "code": """def calculate(user_expr):
    # Remote Code Execution vulnerability
    return eval(user_expr)
""",
        "expected_categories": ["Security"],
        "expected_keywords": ["eval", "exec", "code execution"],
    },
    {
        "name": "bare_except_sample",
        "file_path": "handlers/data.py",
        "code": """def process_data(records):
    try:
        for r in records:
            save_record(r)
    except:
        pass
""",
        "expected_categories": ["Code Quality"],
        "expected_keywords": ["except"],
    },
    {
        "name": "http_no_timeout_sample",
        "file_path": "clients/api.py",
        "code": """import requests

def fetch_external_data(endpoint_url):
    # Missing timeout parameter
    response = requests.get(endpoint_url)
    return response.json()
""",
        "expected_categories": ["Code Quality"],
        "expected_keywords": ["timeout", "http"],
    },
    {
        "name": "god_function_sample",
        "file_path": "legacy/monolith.py",
        "code": """def massive_god_function(data_input):
""" + "\n".join([f"    x_{i} = {i} * 2" for i in range(55)]) + """
    return sum([x_i for x_i in range(55)])
""",
        "expected_categories": ["Code Quality"],
        "expected_keywords": ["god function"],
    },
    {
        "name": "clean_sample",
        "file_path": "services/user_service.py",
        "code": """import logging
from typing import Optional

logger = logging.getLogger(__name__)

def get_user_by_id(db, user_id: int) -> Optional[dict]:
    query = "SELECT id, username FROM users WHERE id = %s"
    cursor = db.cursor()
    cursor.execute(query, (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {"id": row[0], "username": row[1]}
""",
        "expected_categories": [],
        "expected_keywords": [],
    },
]


def test_eval_baseline_suite():
    sec_agent = SecurityAuditorAgent()
    qual_agent = QualityAuditorAgent()

    total_expected = 0
    total_true_positives = 0
    total_false_positives = 0
    total_false_negatives = 0

    results_detail = []

    for sample in BENCHMARK_SAMPLES:
        file_path = sample["file_path"]
        code = sample["code"]
        exp_cats = sample["expected_categories"]
        exp_kw = sample["expected_keywords"]

        sec_issues = sec_agent.analyze(file_path, code)
        qual_issues = qual_agent.analyze(file_path, code)
        all_issues = sec_issues + qual_issues

        if exp_cats:
            total_expected += 1
            # Check if any detected issue matches expected category & keywords
            found_match = False
            for issue in all_issues:
                title_desc = f"{issue.title} {issue.description}".lower()
                kw_match = any(k in title_desc for k in exp_kw) if exp_kw else True
                cat_match = issue.category in exp_cats or "Security" in exp_cats
                if kw_match and cat_match:
                    found_match = True
                    break

            if found_match:
                total_true_positives += 1
            else:
                total_false_negatives += 1
        else:
            # Clean file sample - any issue is a false positive
            if all_issues:
                total_false_positives += len(all_issues)

        results_detail.append({
            "sample_name": sample["name"],
            "detected_issues_count": len(all_issues),
            "expected_has_issue": bool(exp_cats),
        })

    precision = (
        total_true_positives / (total_true_positives + total_false_positives)
        if (total_true_positives + total_false_positives) > 0
        else 1.0
    )
    recall = (
        total_true_positives / (total_true_positives + total_false_negatives)
        if (total_true_positives + total_false_negatives) > 0
        else 1.0
    )
    f1_score = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    baseline_metrics = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1_score, 4),
        "total_true_positives": total_true_positives,
        "total_false_positives": total_false_positives,
        "total_false_negatives": total_false_negatives,
        "benchmark_samples_count": len(BENCHMARK_SAMPLES),
        "results_detail": results_detail,
    }

    out_path = os.path.join(os.path.dirname(__file__), "eval_baseline_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(baseline_metrics, f, indent=2)

    assert recall >= 0.85, f"Baseline recall must be at least 85% (got {recall * 100:.1f}%)"
    assert precision >= 0.80, f"Baseline precision must be at least 80% (got {precision * 100:.1f}%)"


def test_secret_redaction_verification():
    raw_snippet = 'API_KEY = "sk-live-12345678901234567890"'
    redacted = redact_secret_in_snippet(raw_snippet)
    assert "sk-live-12345678901234567890" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_path_traversal_sandboxing():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    scanner = CodebaseScanner(current_dir)

    with pytest.raises(ValueError, match="Path traversal attempt blocked"):
        scanner.read_file("../../outside.py")

    with pytest.raises(ValueError, match="Path traversal attempt blocked"):
        scanner.write_file("../../../malicious.sh", "echo hacked")
