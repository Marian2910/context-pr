import pytest
from pathlib import Path
from typer.testing import CliRunner

from contextpr.cli import app
from contextpr.config import Settings
from contextpr.integrations.git_history import GitHistorySyncResult
from contextpr.integrations.github import GitHubHistorySyncResult
from contextpr.integrations.sonarqube import SonarProjectHistorySyncResult
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


def _settings_env(**overrides: object) -> object:
    return Settings(
        github_app_id="12345",
        github_installation_id="67890",
        github_private_key="-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----",
        github_repository="octo/example",
        sonar_token="sonar-token",
        sonar_project_key="contextpr",
        **overrides,
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


def test_analyze_syncs_local_history_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_calls: list[str] = []

    class FakeSonarClient:
        def sync_project_issue_history(self, *, store: object, repository_key: str) -> SonarProjectHistorySyncResult:
            sync_calls.append(repository_key)
            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                issues_seen=2,
                issues_upserted=2,
                observations_recorded=2,
                latest_update="2026-05-16T10:00:00+00:00",
            )

    class FakeGitHistorySyncer:
        def __init__(self, repository_path: Path) -> None:
            self.repository_path = repository_path

        def sync_repository_history(self, *, store: object, repository_key: str) -> GitHistorySyncResult:
            sync_calls.append(f"git:{repository_key}")
            return GitHistorySyncResult(
                repository_key=repository_key,
                commits_seen=3,
                commits_upserted=3,
                touches_recorded=4,
                latest_commit_sha="abc123",
                latest_authored_at="2026-05-16T09:00:00+00:00",
            )

    class FakeGitHubClient:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def sync_repository_history(self, *, store: object, repository_key: str) -> GitHubHistorySyncResult:
            sync_calls.append(f"github:{repository_key}")
            return GitHubHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                pull_requests_seen=2,
                pull_requests_upserted=2,
                files_recorded=3,
                review_comments_recorded=2,
                latest_update="2026-05-16T10:30:00+00:00",
            )

    monkeypatch.setattr(
        "contextpr.cli.Settings.from_env",
        lambda *_args, **_kwargs: _settings_env(
            local_history_enabled=True,
            local_history_db_path=tmp_path / "cli-history.db",
        ),
    )
    monkeypatch.setattr("contextpr.cli.AnalysisService", lambda **_: FakeService())
    monkeypatch.setattr("contextpr.cli.GitHubClient", FakeGitHubClient)
    monkeypatch.setattr("contextpr.cli.SonarQubeClient", lambda settings: FakeSonarClient())
    monkeypatch.setattr("contextpr.cli.GitHistorySyncer", FakeGitHistorySyncer)
    monkeypatch.setattr("contextpr.cli.IssueEnricher", lambda **_: object())

    result = runner.invoke(app, ["analyze", "--pr-number", "123", "--dry-run"])

    assert result.exit_code == 0
    assert sync_calls == ["octo/example", "git:octo/example", "github:octo/example"]


def test_sync_history_command_runs_all_local_syncers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_calls: list[str] = []

    class FakeSonarClient:
        def sync_project_issue_history(self, *, store: object, repository_key: str) -> SonarProjectHistorySyncResult:
            sync_calls.append("sonar")
            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                issues_seen=1,
                issues_upserted=1,
                observations_recorded=1,
                latest_update="2026-05-16T10:00:00+00:00",
            )

    class FakeGitHistorySyncer:
        def __init__(self, repository_path: Path) -> None:
            self.repository_path = repository_path

        def sync_repository_history(self, *, store: object, repository_key: str) -> GitHistorySyncResult:
            sync_calls.append("git")
            return GitHistorySyncResult(
                repository_key=repository_key,
                commits_seen=1,
                commits_upserted=1,
                touches_recorded=1,
                latest_commit_sha="abc123",
                latest_authored_at="2026-05-16T09:00:00+00:00",
            )

    class FakeGitHubClient:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def sync_repository_history(self, *, store: object, repository_key: str) -> GitHubHistorySyncResult:
            sync_calls.append("github")
            return GitHubHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                pull_requests_seen=1,
                pull_requests_upserted=1,
                files_recorded=1,
                review_comments_recorded=1,
                latest_update="2026-05-16T10:30:00+00:00",
            )

    monkeypatch.setattr(
        "contextpr.cli.Settings.from_env",
        lambda *_args, **_kwargs: _settings_env(
            local_history_enabled=True,
            local_history_db_path=tmp_path / "cli-history.db",
        ),
    )
    monkeypatch.setattr("contextpr.cli.GitHubClient", FakeGitHubClient)
    monkeypatch.setattr("contextpr.cli.SonarQubeClient", lambda settings: FakeSonarClient())
    monkeypatch.setattr("contextpr.cli.GitHistorySyncer", FakeGitHistorySyncer)

    result = runner.invoke(app, ["sync-history"])

    assert result.exit_code == 0
    assert sync_calls == ["sonar", "git", "github"]
    assert "synchronized local history for octo/example" in result.output.lower()
