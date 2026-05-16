from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from contextpr.enrichment.history import GlobalDatasetHistoryRetriever
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    HistoryStore,
    SyncStateRecord,
)

LOCAL_GIT_SYNC_SOURCE = "local_git_history"


@dataclass(frozen=True, slots=True)
class GitHistorySyncResult:
    repository_key: str
    commits_seen: int
    commits_upserted: int
    touches_recorded: int
    latest_commit_sha: str | None
    latest_authored_at: str | None


class GitHistorySyncer:
    def __init__(self, repository_path: Path) -> None:
        self._repository_path = repository_path

    def sync_repository_history(
        self,
        *,
        store: HistoryStore,
        repository_key: str,
    ) -> GitHistorySyncResult:
        with store.acquire_repository_lock(repository_key):
            previous_state = store.get_sync_state(repository_key, LOCAL_GIT_SYNC_SOURCE)
            previous_commit_sha = previous_state.cursor if previous_state is not None else None
            commit_shas = self._commit_shas_since(previous_commit_sha)

            commits_seen = len(commit_shas)
            commits_upserted = 0
            touches_recorded = 0
            latest_commit_sha = previous_commit_sha
            latest_authored_at = previous_state.updated_at if previous_state is not None else None

            for commit_sha in commit_shas:
                commit_record, touches = self._load_commit(commit_sha)
                store.upsert_git_commit(repository_key, commit_record, touches=touches)
                commits_upserted += 1
                touches_recorded += len(touches)
                latest_commit_sha = commit_sha
                latest_authored_at = commit_record.authored_at

            if latest_commit_sha is not None:
                store.upsert_sync_state(
                    SyncStateRecord(
                        repository_key=repository_key,
                        source_name=LOCAL_GIT_SYNC_SOURCE,
                        cursor=latest_commit_sha,
                        updated_at=latest_authored_at,
                    )
                )

            return GitHistorySyncResult(
                repository_key=repository_key,
                commits_seen=commits_seen,
                commits_upserted=commits_upserted,
                touches_recorded=touches_recorded,
                latest_commit_sha=latest_commit_sha,
                latest_authored_at=latest_authored_at,
            )

    def _commit_shas_since(self, previous_commit_sha: str | None) -> list[str]:
        if previous_commit_sha:
            args = [
                "git",
                "rev-list",
                "--reverse",
                f"{previous_commit_sha}..HEAD",
            ]
        else:
            args = ["git", "rev-list", "--reverse", "HEAD"]
        completed = self._run_git(args)
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    def _load_commit(self, commit_sha: str) -> tuple[GitCommitRecord, tuple[GitFileTouchRecord, ...]]:
        meta = self._run_git(
            [
                "git",
                "show",
                "--quiet",
                "--format=%H%n%aI%n%s",
                commit_sha,
            ]
        )
        meta_lines = [line for line in meta.stdout.splitlines()]
        if len(meta_lines) < 3:
            raise RuntimeError(f"Unexpected git show output for commit {commit_sha!r}.")
        commit_sha_value = meta_lines[0].strip()
        authored_at = meta_lines[1].strip()
        message = "\n".join(meta_lines[2:]).strip()
        classification = self._classify_commit_message(message)

        files_output = self._run_git(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "--root",
                "-r",
                commit_sha,
            ]
        )
        touches = tuple(
            GitFileTouchRecord(
                commit_sha=commit_sha_value,
                file_path=file_path,
                module_family=GlobalDatasetHistoryRetriever._path_family(file_path) or None,
            )
            for file_path in (
                line.strip()
                for line in files_output.stdout.splitlines()
            )
            if file_path
        )

        return (
            GitCommitRecord(
                commit_sha=commit_sha_value,
                authored_at=authored_at,
                message=message,
                classification=classification,
            ),
            touches,
        )

    @staticmethod
    def _classify_commit_message(message: str) -> str:
        normalized = message.strip().lower()
        if any(token in normalized for token in ("refactor", "cleanup", "simplif")):
            return "refactor"
        if any(token in normalized for token in ("fix", "bug", "hotfix")):
            return "fix"
        if any(token in normalized for token in ("test", "spec")):
            return "test"
        if any(token in normalized for token in ("doc", "readme")):
            return "docs"
        if any(token in normalized for token in ("build", "ci", "workflow", "pipeline")):
            return "build"
        return "unknown"

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=self._repository_path,
            check=True,
            capture_output=True,
            text=True,
        )
