import pytest
from devwatch.agents.planner import PlannerAgent
from devwatch.agents.security import SecurityAuditorAgent
from devwatch.agents.quality import QualityAuditorAgent
from devwatch.agents.synthesizer import ReportSynthesizerAgent
from devwatch.crew.orchestrator import CodeReviewCrew
from devwatch.models import ReviewReport, ReviewScope, IssueSeverity, CodeIssue

def test_planner_agent_scopes_codebase(tmp_path):
    (tmp_path / "auth.py").write_text("def login(): pass")
    (tmp_path / "db.py").write_text("def connect(): pass")
    
    planner = PlannerAgent()
    scope = planner.plan_review(str(tmp_path))
    
    assert isinstance(scope, ReviewScope)
    assert scope.target_path == str(tmp_path)
    assert len(scope.files_to_review) >= 2
    assert len(scope.focus_areas) >= 2

def test_security_agent_analyzes_code():
    agent = SecurityAuditorAgent()
    code = "API_KEY = 'sk_live_999999999999'\ncursor.execute(f'SELECT * FROM users WHERE id = {uid}')"
    issues = agent.analyze("src/config.py", code)
    
    assert len(issues) >= 2
    assert any(i.severity == IssueSeverity.CRITICAL for i in issues)

def test_quality_agent_analyzes_code():
    agent = QualityAuditorAgent()
    code = "try:\n    pass\nexcept:\n    pass\nprint('hello')\n"
    issues = agent.analyze("src/app.py", code)
    
    assert len(issues) >= 2
    assert any(i.category == "Code Quality" for i in issues)

def test_synthesizer_agent_renders_report():
    synthesizer = ReportSynthesizerAgent()
    issue = CodeIssue(
        file_path="app.py", line_number=10, severity=IssueSeverity.HIGH,
        category="Security", title="SQL Injection", description="Raw SQL format", suggestion="Use ORM"
    )
    report = ReviewReport(target_path="app.py", issues=[issue])
    markdown = synthesizer.render_markdown(report)
    
    assert "# DevWatch Code Review Report" in markdown
    assert "SQL Injection" in markdown
    assert "HIGH" in markdown

def test_code_review_crew_full_pipeline(tmp_path):
    (tmp_path / "vulnerable.py").write_text("SECRET_KEY = 'sk_live_1234567890abcdef'\ntry:\n    pass\nexcept:\n    pass\n")
    
    crew = CodeReviewCrew()
    report = crew.run(str(tmp_path))
    
    assert isinstance(report, ReviewReport)
    assert report.total_issues >= 2
    assert report.critical_count >= 1
    assert "# DevWatch Code Review Report" in report.summary

def test_llm_integration_mocked(monkeypatch):
    from devwatch.agents import llm
    monkeypatch.setenv("OPENAI_API_KEY", "mock_key")
    assert llm.is_llm_available() is True

    # Mock call_llm_completion — route on user prompt text (unique per agent)
    def mock_completion(prompt, system_prompt=""):
        if "File listing" in prompt or "risk-ranking" in prompt:
            return '{"priority_files": ["src/app.py"], "focus_areas": ["Auth Security", "Data Validation"]}'
        if "vulnerability taxonomy" in prompt:
            return '[{"line_number": 5, "severity": "HIGH", "category": "Security", "title": "Insecure JWT", "description": "No signature check", "suggestion": "Verify JWT signature", "code_snippet": "jwt.decode(token)"}]'
        if "defect taxonomy" in prompt:
            return '[{"line_number": 12, "severity": "MEDIUM", "category": "Code Quality", "title": "Resource Leak", "description": "Unclosed handle", "suggestion": "Use with statement", "code_snippet": "f = open(path)"}]'
        return "Executive summary of risks."

    monkeypatch.setattr(llm, "call_llm_completion", mock_completion)

    security = SecurityAuditorAgent()
    sec_issues = security.analyze("src/app.py", "jwt.decode(token)")
    assert any(i.title == "Insecure JWT" for i in sec_issues)

    quality = QualityAuditorAgent()
    qual_issues = quality.analyze("src/app.py", "f = open(path)")
    assert any(i.title == "Resource Leak" for i in qual_issues)

