from __future__ import annotations

from collections.abc import Mapping

from contextpr.models import ExistingReviewComment, GitHubReviewComment, PullRequestFile
from contextpr.persistence import (
    GitCommitRecord,
    GitFileTouchRecord,
    PullRequestRecord,
)


def optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def map_pull_request_file(item: Mapping[str, object]) -> PullRequestFile | None:
    filename = item.get("filename")
    status = item.get("status")
    patch = item.get("patch")
    if not isinstance(filename, str) or not isinstance(status, str):
        return None
    return PullRequestFile(
        path=filename,
        status=status,
        patch=patch if isinstance(patch, str) else None,
    )


def map_existing_review_comment(item: Mapping[str, object]) -> ExistingReviewComment | None:
    comment_id = item.get("id")
    path = item.get("path")
    body = item.get("body")
    line = item.get("line")
    user = item.get("user")
    author_login = user.get("login") if isinstance(user, Mapping) else None
    if not (
        isinstance(comment_id, int)
        and isinstance(path, str)
        and isinstance(body, str)
        and (line is None or isinstance(line, int))
        and isinstance(author_login, str)
    ):
        return None
    return ExistingReviewComment(
        comment_id=comment_id,
        path=path,
        line=line,
        body=body,
        author_login=author_login,
    )


def map_pull_request_record(payload: Mapping[str, object]) -> PullRequestRecord | None:
    pr_number = payload.get("number")
    title = payload.get("title")
    if not isinstance(pr_number, int) or not isinstance(title, str):
        return None
    return PullRequestRecord(
        pr_number=pr_number,
        title=title,
        body=optional_string(payload, "body"),
        state=optional_string(payload, "state"),
        merged_at=optional_string(payload, "merged_at"),
        updated_at=optional_string(payload, "updated_at"),
    )


def map_commit_history(
    payload: Mapping[str, object],
) -> tuple[GitCommitRecord, tuple[GitFileTouchRecord, ...]] | None:
    commit_sha = optional_string(payload, "sha")
    commit_info = payload.get("commit")
    if commit_sha is None or not isinstance(commit_info, Mapping):
        return None

    commit_message = optional_string(commit_info, "message")
    author_info = commit_info.get("author")
    authored_at = optional_string(author_info, "date") if isinstance(author_info, Mapping) else None
    if commit_message is None or authored_at is None:
        return None

    files_payload = payload.get("files")
    touches: tuple[GitFileTouchRecord, ...] = ()
    if isinstance(files_payload, list):
        touches = tuple(
            GitFileTouchRecord(
                commit_sha=commit_sha,
                file_path=filename,
                module_family=module_family(filename),
            )
            for filename in (
                optional_string(item, "filename")
                for item in files_payload
                if isinstance(item, Mapping)
            )
            if filename is not None
        )

    return (
        GitCommitRecord(
            commit_sha=commit_sha,
            authored_at=authored_at,
            message=commit_message,
            classification=classify_commit_message(commit_message),
        ),
        touches,
    )


def classify_commit_message(message: str) -> str:
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


def module_family(file_path: str) -> str | None:
    normalized = file_path.strip().replace("\\", "/")
    if not normalized:
        return None
    parts = [segment for segment in normalized.split("/") if segment]
    if len(parts) < 2:
        return parts[0] if parts else None
    return "/".join(parts[:2])


def review_comment_payload(comment: GitHubReviewComment) -> dict[str, object]:
    payload: dict[str, object] = {
        "path": comment.path,
        "line": comment.line,
        "side": comment.side,
        "body": comment.body,
    }
    if comment.start_line is not None:
        payload["start_line"] = comment.start_line
        payload["start_side"] = comment.start_side or comment.side
    return payload
