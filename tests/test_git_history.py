from __future__ import annotations

import subprocess
from pathlib import Path

from contextpr.integrations.git_history import LOCAL_GIT_SYNC_SOURCE, GitHistorySyncer
from contextpr.persistence import HistoryStore


def test_git_history_sync_persists_commits_touches_and_checkpoint(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_repo(repo_path)
    _commit_file(repo_path, "src/app.py", "print('a')\n", "refactor: simplify app")
    _commit_file(repo_path, "src/app.py", "print('b')\n", "fix: handler bug")
    _commit_file(repo_path, "docs/readme.md", "# docs\n", "docs: update readme")

    store = HistoryStore(tmp_path / "history.db")

    result = GitHistorySyncer(repo_path).sync_repository_history(
        store=store,
        repository_key="octo/example",
    )

    assert result.commits_seen == 3
    assert result.commits_upserted == 3
    assert result.touches_recorded == 3
    assert result.latest_commit_sha is not None
    assert len(store.list_git_commits("octo/example")) == 3
    assert sorted(touch.file_path for touch in store.list_git_file_touches("octo/example")) == [
        "docs/readme.md",
        "src/app.py",
        "src/app.py",
    ]
    checkpoint = store.get_sync_state("octo/example", LOCAL_GIT_SYNC_SOURCE)
    assert checkpoint is not None
    assert checkpoint.cursor == result.latest_commit_sha


def test_git_history_sync_only_processes_new_commits_after_checkpoint(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_repo(repo_path)
    _commit_file(repo_path, "src/app.py", "print('a')\n", "refactor: simplify app")

    store = HistoryStore(tmp_path / "history.db")
    syncer = GitHistorySyncer(repo_path)
    first = syncer.sync_repository_history(store=store, repository_key="octo/example")
    _commit_file(repo_path, "src/app.py", "print('b')\n", "test: add regression coverage")

    second = syncer.sync_repository_history(store=store, repository_key="octo/example")

    assert first.commits_upserted == 1
    assert second.commits_seen == 1
    assert second.commits_upserted == 1
    assert second.touches_recorded == 1
    assert len(store.list_git_commits("octo/example")) == 2


def _init_repo(repo_path: Path) -> None:
    _run(repo_path, ["git", "init"])
    _run(repo_path, ["git", "config", "user.email", "contextpr@example.com"])
    _run(repo_path, ["git", "config", "user.name", "ContextPR"])


def _commit_file(repo_path: Path, relative_path: str, content: str, message: str) -> None:
    target = repo_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _run(repo_path, ["git", "add", relative_path])
    _run(repo_path, ["git", "commit", "-m", message])


def _run(repo_path: Path, args: list[str]) -> None:
    subprocess.run(
        args,
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
