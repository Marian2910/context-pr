from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepositoryRecord:
    repository_id: int
    repository_key: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SyncStateRecord:
    repository_key: str
    source_name: str
    cursor: str | None = None
    updated_at: str | None = None
    metadata_json: str | None = None


@dataclass(frozen=True, slots=True)
class SonarIssueRecord:
    issue_key: str
    rule: str
    issue_type: str
    severity: str
    component: str
    message: str
    tags_json: str | None = None
    clean_code_attribute: str | None = None
    clean_code_attribute_category: str | None = None
    status: str | None = None
    resolution: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    branch: str | None = None
    line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True, slots=True)
class SonarIssueObservationRecord:
    issue_key: str
    observed_at: str
    status: str | None = None
    resolution: str | None = None
    severity: str | None = None
    component: str | None = None
    branch: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class GitCommitRecord:
    commit_sha: str
    authored_at: str
    message: str
    classification: str = "unknown"


@dataclass(frozen=True, slots=True)
class GitFileTouchRecord:
    commit_sha: str
    file_path: str
    module_family: str | None = None


@dataclass(frozen=True, slots=True)
class PullRequestRecord:
    pr_number: int
    title: str
    body: str | None = None
    state: str | None = None
    merged_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class PullRequestFileRecord:
    pr_number: int
    file_path: str


@dataclass(frozen=True, slots=True)
class PullRequestReviewCommentRecord:
    comment_id: int
    pr_number: int
    body: str
    file_path: str | None = None
    line: int | None = None
    author_role: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
