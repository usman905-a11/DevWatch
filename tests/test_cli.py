import pytest
from typer.testing import CliRunner
from devwatch.cli import app

runner = CliRunner()

def test_cli_version_command():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "DevWatch v0.1.0" in result.stdout

def test_cli_help_exposes_canonical_service_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("review", "submit", "job", "resume", "cancel", "serve"):
        assert command in result.stdout

