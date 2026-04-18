import pytest
from typer.testing import CliRunner

from contextpr.cli import app
from contextpr.config import Settings
from contextpr.models import PullRequestRef
from contextpr.services import AnalysisResult

runner = CliRunner()


class FakeService:

    def analyze_pull_request(
        self,
        *,
        pull_request: PullRequestRef,
        dry_run: bool,
    ) -> AnalysisResult:
        return AnalysisResult(
            pull_request=pull_request,
            fetched_issues=2,
            eligible_issues=1,
            deleted_comments=1,
            posted_comments=0 if dry_run else 1,
            dry_run=dry_run,
        )


def test_analyze_command_reports_run_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("contextpr.cli.AnalysisService", lambda **_: FakeService())
    monkeypatch.setattr("contextpr.cli.GitHubClient", lambda settings: object())
    monkeypatch.setattr("contextpr.cli.SonarQubeClient", lambda settings: object())
    monkeypatch.setattr("contextpr.cli.IssueEnricher", lambda **_: object())
    monkeypatch.setattr(
        "contextpr.cli.Settings.from_env",
        lambda *_args, **_kwargs: _settings_env(),
    )

    result = runner.invoke(app, ["analyze", "--pr-number", "123", "--dry-run"])

    assert result.exit_code == 0
    assert "fetched 2 Sonar issues" in result.stdout
    assert "prepared 1 inline comments" in result.stdout
    assert "deleted 1 previous ContextPR comments" in result.stdout
    assert "posted 0." in result.stdout


def _settings_env() -> object:
    return Settings(
        github_app_id="12345",
        github_installation_id="67890",
        github_private_key="-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
        github_repository="octo/example",
        sonar_token="sonar-token",
        sonar_project_key="contextpr",
    )


def test_analyze_requires_pr_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "contextpr.cli.Settings.from_env",
        lambda *_args, **_kwargs: _settings_env(),
    )
    result = runner.invoke(app, ["analyze", "--dry-run"])

    assert result.exit_code != 0
    assert "A pull request number is required" in result.output


def test_cli_help_includes_analyze_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ContextPR" in result.stdout
    assert "analyze" in result.stdout
