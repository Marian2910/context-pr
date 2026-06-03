import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contextpr.cli import app
from contextpr.config import Settings
from contextpr.integrations.github import GitHubCommitHistorySyncResult, GitHubHistorySyncResult
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


def test_analyze_pr_command_reports_run_summary(
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

    result = runner.invoke(app, ["analyze", "pr", "123", "--dry-run"])

    assert result.exit_code == 0
    assert "ContextPR analyzed PR #123" in result.stdout


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


def test_help_command_prints_user_command_guide() -> None:
    result = runner.invoke(app, ["help"])

    assert result.exit_code == 0
    assert "ContextPR" in result.stdout
    assert "Common commands:" in result.stdout
    assert "context-pr init" in result.stdout
    assert "context-pr sync" in result.stdout
    assert "context-pr analyze pr 3 --no-dry-run" in result.stdout
    assert "context-pr uninstall" in result.stdout


def test_analyze_syncs_local_history_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_calls: list[str] = []

    class FakeSonarClient:
        def sync_project_issue_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> SonarProjectHistorySyncResult:
            sync_calls.append(repository_key)
            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                issues_seen=2,
                issues_upserted=2,
                observations_recorded=2,
                latest_update="2026-05-16T10:00:00+00:00",
            )

    class FakeGitHubClient:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def sync_commit_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> GitHubCommitHistorySyncResult:
            sync_calls.append(f"git:{repository_key}")
            return GitHubCommitHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                commits_seen=3,
                commits_upserted=3,
                touches_recorded=4,
                latest_commit_sha="abc123",
                latest_authored_at="2026-05-16T09:00:00+00:00",
            )

        def sync_repository_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> GitHubHistorySyncResult:
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
        def sync_project_issue_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> SonarProjectHistorySyncResult:
            sync_calls.append("sonar")
            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                issues_seen=1,
                issues_upserted=1,
                observations_recorded=1,
                latest_update="2026-05-16T10:00:00+00:00",
            )

    class FakeGitHubClient:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def sync_commit_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> GitHubCommitHistorySyncResult:
            sync_calls.append("git")
            return GitHubCommitHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                commits_seen=1,
                commits_upserted=1,
                touches_recorded=1,
                latest_commit_sha="abc123",
                latest_authored_at="2026-05-16T09:00:00+00:00",
            )

        def sync_repository_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> GitHubHistorySyncResult:
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

    result = runner.invoke(app, ["sync-history"])

    assert result.exit_code == 0
    assert sync_calls == ["sonar", "git", "github"]
    assert "synchronized local history for octo/example" in result.output.lower()


def test_sync_alias_runs_all_local_syncers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_calls: list[str] = []

    class FakeSonarClient:
        def sync_project_issue_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> SonarProjectHistorySyncResult:
            sync_calls.append("sonar")
            return SonarProjectHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                issues_seen=1,
                issues_upserted=1,
                observations_recorded=1,
                latest_update="2026-05-16T10:00:00+00:00",
            )

    class FakeGitHubClient:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def sync_commit_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> GitHubCommitHistorySyncResult:
            sync_calls.append("git")
            return GitHubCommitHistorySyncResult(
                repository_key=repository_key,
                pages_fetched=1,
                commits_seen=1,
                commits_upserted=1,
                touches_recorded=1,
                latest_commit_sha="abc123",
                latest_authored_at="2026-05-16T09:00:00+00:00",
            )

        def sync_repository_history(
            self,
            *,
            store: object,
            repository_key: str,
        ) -> GitHubHistorySyncResult:
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

    result = runner.invoke(app, ["sync"])

    assert result.exit_code == 0
    assert sync_calls == ["sonar", "git", "github"]


def test_init_creates_repo_state_gitignore_hook_and_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / ".env").write_text("# Existing app config\nEXISTING=value\n", encoding="utf-8")
    private_key = tmp_path / "app-key.pem"
    private_key.write_text(
        "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    result = runner.invoke(
        app,
        ["init"],
        input=f"12345\n67890\n{private_key}\nsonar-token\nocto/example\ncontextpr\nplatform\n",
        env={},
    )

    assert result.exit_code == 0
    assert (repo / ".context-pr" / "config.toml").is_file()
    assert ".context-pr/" in (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in (repo / ".gitignore").read_text(encoding="utf-8")
    assert "secrets/" in (repo / ".gitignore").read_text(encoding="utf-8")
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert "ContextPR refuses to commit local state or secrets" in hook.read_text(
        encoding="utf-8"
    )
    env = (repo / ".env").read_text(encoding="utf-8")
    assert "# Existing app config" in env
    assert "EXISTING=value" in env
    assert "CONTEXTPR_GITHUB_APP_ID=12345" in env
    assert "CONTEXTPR_GITHUB_INSTALLATION_ID=67890" in env
    assert "CONTEXTPR_SONAR_TOKEN=sonar-token" in env
    assert "CONTEXTPR_LOCAL_HISTORY_DB_PATH=" in env
    assert (repo / "secrets" / "GITHUB_APP_PRIVATE_KEY.pem").read_text(
        encoding="utf-8"
    ) == private_key.read_text(encoding="utf-8")


def test_guard_passes_when_local_paths_are_not_tracked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["guard"], env={})

    assert result.exit_code == 0
    assert "guard passed" in result.output


def test_guard_fails_when_local_paths_are_tracked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / ".env").write_text("CONTEXTPR_GITHUB_TOKEN=secret\n", encoding="utf-8")
    subprocess.run(["git", "add", ".env"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["guard"], env={})

    assert result.exit_code != 0
    assert ".env" in result.output


def test_update_runs_pip_upgrade_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> FakeCompletedProcess:
        calls.append(command)
        assert check is False
        return FakeCompletedProcess()

    monkeypatch.setattr("contextpr.cli.sys.executable", "/opt/contextpr/bin/python")
    monkeypatch.setattr("contextpr.cli.subprocess.run", fake_run)

    result = runner.invoke(app, ["update"], env={})

    assert result.exit_code == 0
    assert calls == [
        [
            "/opt/contextpr/bin/python",
            "-m",
            "pip",
            "install",
            "--upgrade",
            "git+https://github.com/Marian2910/context-pr.git",
        ]
    ]


def test_update_uses_pipx_when_running_from_pipx_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> FakeCompletedProcess:
        calls.append(command)
        assert check is False
        return FakeCompletedProcess()

    monkeypatch.setattr(
        "contextpr.cli.sys.executable",
        "/Users/example/.local/pipx/venvs/contextpr/bin/python",
    )
    monkeypatch.setattr("contextpr.cli.subprocess.run", fake_run)

    result = runner.invoke(app, ["update"], env={})

    assert result.exit_code == 0
    assert calls == [["pipx", "upgrade", "contextpr"]]


def test_uninstall_runs_pip_uninstall_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> FakeCompletedProcess:
        calls.append(command)
        assert check is False
        return FakeCompletedProcess()

    monkeypatch.setattr("contextpr.cli.sys.executable", "/opt/contextpr/bin/python")
    monkeypatch.setattr("contextpr.cli.subprocess.run", fake_run)

    result = runner.invoke(app, ["uninstall"], env={})

    assert result.exit_code == 0
    assert calls == [["/opt/contextpr/bin/python", "-m", "pip", "uninstall", "-y", "contextpr"]]


def test_uninstall_uses_pipx_when_running_from_pipx_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> FakeCompletedProcess:
        calls.append(command)
        assert check is False
        return FakeCompletedProcess()

    monkeypatch.setattr(
        "contextpr.cli.sys.executable",
        "/Users/example/.local/pipx/venvs/contextpr/bin/python",
    )
    monkeypatch.setattr("contextpr.cli.subprocess.run", fake_run)

    result = runner.invoke(app, ["uninstall"], env={})

    assert result.exit_code == 0
    assert calls == [["pipx", "uninstall", "contextpr"]]
