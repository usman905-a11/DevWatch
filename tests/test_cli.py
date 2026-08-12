import pytest
from typer.testing import CliRunner
from devwatch.cli import app

runner = CliRunner()

def test_cli_version_command():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "DevWatch v0.1.0" in result.stdout

def test_cli_review_command(tmp_path):
    from unittest.mock import patch, MagicMock, AsyncMock
    from devwatch.models import ReviewReport

    (tmp_path / "app.py").write_text("SECRET_KEY = 'sk_live_1234567890abcdef'\n")
    output_file = tmp_path / "report.md"

    mock_report = ReviewReport(
        target_path=str(tmp_path),
        issues=[],
        summary="# DevWatch Code Review Report\n\n✅ Security check complete."
    )

    with patch("devwatch.cli.ReviewPipeline") as mock_pipeline_cls:
        mock_instance = MagicMock()
        mock_instance.execute = AsyncMock(return_value=mock_report)
        mock_pipeline_cls.return_value = mock_instance

        result = runner.invoke(app, ["review", str(tmp_path), "--output", str(output_file)])
        assert result.exit_code == 0
        assert "DevWatch Code Review Report" in result.stdout
        assert output_file.exists()
        assert "# DevWatch Code Review Report" in output_file.read_text()

