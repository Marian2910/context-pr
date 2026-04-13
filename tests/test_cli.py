"""Tests for the ContextPR CLI."""

from typer.testing import CliRunner

from contextpr.cli import app

runner = CliRunner()


def test_cli_help_includes_analyze_command() -> None:
    """The root help output should expose the analyze command."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ContextPR" in result.stdout
    assert "analyze" in result.stdout


def test_analyze_command_reports_placeholder_status() -> None:
    """The analyze command should confirm the scaffold is wired up."""
    result = runner.invoke(app, ["analyze", "--pr-number", "123", "--dry-run"])

    assert result.exit_code == 0
    assert "Placeholder analyze command invoked for PR #123" in result.stdout
