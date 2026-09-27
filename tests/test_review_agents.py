import pytest

from devwatch.models import CodeIssue, IssueSeverity, VerificationStatus
from devwatch.providers.fake_provider import FakeLLMProvider
from devwatch.review.agents import RiskPlannerAgent, RoleReviewAgent, StrictVerifierAgent
from devwatch.review.models import SpecialistRole


pytestmark = pytest.mark.asyncio


async def test_planner_fallback_routes_only_relevant_specialists():
    """A provider outage must preserve bounded deterministic routing, not run all roles."""
    planner = RiskPlannerAgent(provider=FakeLLMProvider(available=False))

    tasks = await planner.execute(
        {
            "files": ["auth.py", "math.py"],
            "changed_regions": [],
            "tool_evidence": [],
        }
    )

    by_role = {task.specialist: task.files for task in tasks}
    assert by_role[SpecialistRole.CORRECTNESS] == ["auth.py", "math.py"]
    assert by_role[SpecialistRole.SECURITY] == ["auth.py"]
    assert SpecialistRole.PERFORMANCE not in by_role


async def test_specialist_maps_structured_llm_output_to_finding():
    """A specialist response without a valid file assignment must not leak into reports."""
    provider = FakeLLMProvider(
        default_content=(
            '{"issues":[{"file_path":"app.py","line_number":1,'
            '"severity":"HIGH","category":"Correctness","title":"Wrong branch",'
            '"description":"The changed condition reverses the result.",'
            '"suggestion":"Restore the expected predicate.",'
            '"code_snippet":"if not ready:","confidence_score":0.9}]}'
        )
    )
    agent = RoleReviewAgent(SpecialistRole.CORRECTNESS, provider=provider)

    issues = await agent.execute(
        {
            "task": {"focus": "changed branches"},
            "files": {"app.py": "if not ready:\n    return value\n"},
            "context_files": {},
            "tool_evidence": [],
        }
    )

    assert len(issues) == 1
    assert issues[0].file_path == "app.py"
    assert issues[0].specialist == SpecialistRole.CORRECTNESS.value
    assert issues[0].source_type == "agent"


async def test_verifier_attaches_status_and_confidence_by_finding_id():
    """Strict gating depends on the verifier returning an identity-bound confidence."""
    issue = CodeIssue(
        file_path="app.py",
        line_number=1,
        severity=IssueSeverity.HIGH,
        category="Security",
        title="Unsafe command",
        description="Input reaches shell.",
        suggestion="Use argv.",
        code_snippet="run(value)",
    )
    provider = FakeLLMProvider(
        default_content=(
            '{"verifications":[{"finding_id":"'
            + issue.finding_id
            + '","status":"ACCEPTED","is_true_positive":true,'
            '"confidence":0.94,"reasoning":"The data flow is direct."}]}'
        )
    )
    verifier = StrictVerifierAgent(provider=provider)

    verified = await verifier.execute(
        {"file_path": "app.py", "code_content": "run(value)\n", "issues": [issue]}
    )

    assert len(verified) == 1
    assert verified[0].verification_status == VerificationStatus.ACCEPTED
    assert verified[0].verification_confidence == 0.94
