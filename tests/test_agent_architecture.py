import pytest
from devwatch.agents.base import BaseAgent, AgentMetadata
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.verifier import VerificationAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.agents.registry import AgentRegistry, agent_registry
from devwatch.agents.fake_agent import FakeAgent
from devwatch.prompts.registry import PromptRegistry, prompt_registry, PromptTemplate
from devwatch.providers.fake_provider import FakeLLMProvider


@pytest.fixture(autouse=True)
def reset_registries():
    agent_registry.clear()
    yield
    agent_registry.clear()


def test_base_agent_interface_compliance():
    agents = [
        PlannerAgent(),
        SecurityAuditorAgent(),
        QualityAuditorAgent(),
        VerificationAgent(),
        ReportSynthesizerAgent(),
    ]

    for agent in agents:
        assert isinstance(agent, BaseAgent)
        meta = agent.metadata
        assert isinstance(meta, AgentMetadata)
        assert meta.agent_id is not None
        assert meta.version == "1.0.0"
        assert meta.prompt_id is not None
        assert meta.prompt_version == "1.0.0"
        assert meta.purpose is not None


def test_agent_registry_operations():
    reg = AgentRegistry()
    fake_planner = FakeAgent(agent_id="planner_agent")
    fake_sec = FakeAgent(agent_id="security_auditor")

    reg.register(fake_planner)
    reg.register(fake_sec)

    assert len(reg.list_agents()) == 2
    assert reg.get("planner_agent") == fake_planner
    assert reg.get("security_auditor") == fake_sec

    with pytest.raises(KeyError):
        reg.get("non_existent_agent")


@pytest.mark.asyncio
async def test_fake_agent_substitution_in_orchestrator(tmp_path):
    from devwatch.pipeline.dag import ReviewPipeline
    from devwatch.models import ReviewScope
    (tmp_path / "main.py").write_text("print('hello')")

    fake_planner = FakeAgent(
        agent_id="planner_agent",
        canned_output=ReviewScope(target_path=str(tmp_path), files_to_review=["main.py"], focus_areas=["General"])
    )
    fake_sec = FakeAgent(agent_id="security_auditor", canned_output=[])
    fake_qual = FakeAgent(agent_id="quality_auditor", canned_output=[])

    pipeline = ReviewPipeline(
        planner=fake_planner,
        security_agent=fake_sec,
        quality_agent=fake_qual,
    )

    report = await pipeline.execute(str(tmp_path))
    assert report is not None
    assert len(fake_sec.executed_contexts) >= 1
    assert len(fake_qual.executed_contexts) >= 1



def test_prompt_registry_snapshot_and_rendering():
    reg = PromptRegistry()

    # Test prompt template snapshot existence
    for pid in ["planner:v1", "security:v1", "quality:v1", "verifier:v1", "synthesizer:v1"]:
        prompt = reg.get(pid)
        assert prompt is not None
        assert prompt.prompt_id == pid
        assert len(prompt.template) > 50

    # Custom prompt rendering with template vars
    custom_template = PromptTemplate(
        prompt_id="test:v1",
        version="1.0.0",
        template="Hello {name}, reviewing file {file_path}",
        description="Test template",
    )
    reg.register(custom_template)

    rendered = reg.render("test:v1", {"name": "Auditor", "file_path": "app.py"})
    assert rendered == "Hello Auditor, reviewing file app.py"

    # Missing template variable raises ValueError
    with pytest.raises(ValueError) as exc_info:
        reg.render("test:v1", {"name": "Auditor"})
    assert "Missing variable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_agent_constructor_dependency_injection(tmp_path):
    (tmp_path / "sample.py").write_text("x = 10")
    fake_provider = FakeLLMProvider(default_content='{"priority_files": ["sample.py"], "focus_areas": ["General"]}')

    # Inject custom fake provider and prompt registry
    planner = PlannerAgent(provider=fake_provider, prompt_reg=prompt_registry)
    scope = await planner.execute({"target_path": str(tmp_path)})

    assert scope is not None
    assert scope.files_to_review == ["sample.py"]
    assert len(fake_provider.calls) == 1
