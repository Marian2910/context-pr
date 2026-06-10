from __future__ import annotations

from datetime import timedelta

import contextpr.enrichment.history.local.sonar_scoring as sonar_scoring
from contextpr.enrichment.history.types import (
    FIX_REFERENCE_LOOKBACK_DAYS,
    FIX_REFERENCE_PR_LIMIT,
    FIX_REFERENCE_RECORD_LIMIT,
    MAX_FIX_ATTRIBUTION_DELAY_DAYS,
    MIN_FIX_REFERENCE_MATCH_SCORE,
    MIN_FIX_REFERENCE_RECORD_SCORE,
    MIN_FIX_REFERENCE_WINDOW_PRS,
    HistoricalFixReference,
)
from contextpr.enrichment.history.utils import (
    component_path,
    parse_timestamp,
    path_family,
    path_scope,
)
from contextpr.models import SonarIssue
from contextpr.persistence import (
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    SonarIssueRecord,
)


def fix_references(
    *,
    store: HistoryStore,
    repository_key: str,
    issue: SonarIssue,
    similar: list[SonarIssueRecord],
    top_k: int = 3,
) -> tuple[HistoricalFixReference, ...]:
    pull_requests = bounded_fix_reference_pull_requests(
        [pr for pr in store.list_pull_requests(repository_key) if pr.merged_at is not None]
    )
    if not pull_requests:
        return ()
    files_by_pr = {
        pr.pr_number: store.list_pull_request_files(repository_key, pr.pr_number)
        for pr in pull_requests
    }
    candidate_records = fix_reference_candidate_records(
        store=store,
        repository_key=repository_key,
        issue=issue,
        similar=similar,
    )
    references: list[HistoricalFixReference] = []
    seen_prs: set[int] = set()
    for record in candidate_records:
        if sonar_scoring.disposition_bucket(record) != "resolved":
            continue
        reference = fix_reference_for_record(
            repository_key=repository_key,
            issue=issue,
            record=record,
            pull_requests=pull_requests,
            files_by_pr=files_by_pr,
        )
        if reference is None or reference.pr_number in seen_prs:
            continue
        references.append(reference)
        seen_prs.add(reference.pr_number)
        if len(references) >= top_k:
            break
    return tuple(references)


def fix_reference_candidate_records(
    *,
    store: HistoryStore,
    repository_key: str,
    issue: SonarIssue,
    similar: list[SonarIssueRecord],
) -> list[SonarIssueRecord]:
    candidates: dict[str, tuple[SonarIssueRecord, float]] = {
        record.issue_key: (record, 1.0) for record in similar
    }
    for record in store.list_sonar_issues(repository_key):
        score = fix_reference_record_score(issue, record)
        if score < MIN_FIX_REFERENCE_RECORD_SCORE:
            continue
        existing = candidates.get(record.issue_key)
        if existing is None or score > existing[1]:
            candidates[record.issue_key] = (record, score)
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            item[1],
            item[0].updated_at or "",
            item[0].created_at or "",
            item[0].issue_key,
        ),
        reverse=True,
    )
    return [record for record, _score in ranked[:FIX_REFERENCE_RECORD_LIMIT]]


def fix_reference_record_score(issue: SonarIssue, record: SonarIssueRecord) -> float:
    if sonar_scoring.disposition_bucket(record) != "resolved":
        return 0.0
    rule_score = sonar_scoring.rule_similarity(issue, record)
    location_score = sonar_scoring.location_similarity(issue, record)
    if rule_score <= 0.0 and location_score <= 0.0:
        return 0.0
    return round((0.6 * rule_score) + (0.4 * location_score), 4)


def fix_reference_for_record(
    *,
    repository_key: str,
    issue: SonarIssue,
    record: SonarIssueRecord,
    pull_requests: list[PullRequestRecord],
    files_by_pr: dict[int, list[PullRequestFileRecord]],
) -> HistoricalFixReference | None:
    resolved_at = parse_timestamp(record.updated_at)
    if resolved_at is None:
        return None
    record_path = component_path(record.component)
    candidates: list[tuple[PullRequestRecord, int]] = []
    for pull_request in pull_requests:
        merged_at = parse_timestamp(pull_request.merged_at)
        if merged_at is None or merged_at > resolved_at:
            continue
        age = resolved_at - merged_at
        if age < timedelta(0) or age > timedelta(days=MAX_FIX_ATTRIBUTION_DELAY_DAYS):
            continue
        if not pull_request_touches_path(files_by_pr.get(pull_request.pr_number, []), record_path):
            continue
        candidates.append((pull_request, int(age.total_seconds())))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[1], -item[0].pr_number))
    pull_request = candidates[0][0]
    files = files_by_pr.get(pull_request.pr_number, [])
    match_score = fix_reference_match_score(issue, record, files)
    if match_score < MIN_FIX_REFERENCE_MATCH_SCORE:
        return None
    return HistoricalFixReference(
        pr_number=pull_request.pr_number,
        pr_title=pull_request.title,
        pr_url=pull_request_url(repository_key, pull_request.pr_number),
        file_url=f"{pull_request_url(repository_key, pull_request.pr_number)}/files",
        file_path=record_path,
        resolved_at=record.updated_at or "",
        match_score=match_score,
        evidence=fix_reference_evidence(issue, record, files),
    )


def pull_request_touches_path(files: list[PullRequestFileRecord], issue_path: str) -> bool:
    return any(file_record.file_path == issue_path for file_record in files)


def bounded_fix_reference_pull_requests(
    pull_requests: list[PullRequestRecord],
) -> list[PullRequestRecord]:
    dated_pull_requests = [
        (pull_request, merged_at)
        for pull_request in pull_requests
        if (merged_at := parse_timestamp(pull_request.merged_at)) is not None
    ]
    if not dated_pull_requests:
        return []
    dated_pull_requests.sort(key=lambda item: (item[1], item[0].pr_number), reverse=True)
    newest_merge = dated_pull_requests[0][1]
    cutoff = newest_merge - timedelta(days=FIX_REFERENCE_LOOKBACK_DAYS)
    time_window = [
        pull_request for pull_request, merged_at in dated_pull_requests if merged_at >= cutoff
    ]
    count_window = [
        pull_request for pull_request, _merged_at in dated_pull_requests[:FIX_REFERENCE_PR_LIMIT]
    ]
    if len(time_window) >= MIN_FIX_REFERENCE_WINDOW_PRS:
        return time_window[:FIX_REFERENCE_PR_LIMIT]
    return count_window


def fix_reference_match_score(
    issue: SonarIssue,
    record: SonarIssueRecord,
    files: list[PullRequestFileRecord],
) -> float:
    record_path = component_path(record.component)
    match_score = 0.0
    if record.rule == issue.rule:
        match_score += 0.3
    match_score += location_match_score_bonus(issue.location.path, record_path)
    if any(file_record.file_path == record_path for file_record in files):
        match_score += 0.2
    match_score += 0.15 * sonar_scoring.code_similarity(issue, record)
    if record.line is not None:
        match_score += 0.05
    if not any(is_analysis_config_path(file_record.file_path) for file_record in files):
        match_score += 0.05
    return round(min(match_score, 1.0), 2)


def location_match_score_bonus(issue_path: str, record_path: str) -> float:
    if record_path == issue_path and issue_path:
        return 0.25
    if path_family(record_path) == path_family(issue_path):
        return 0.16
    if path_scope(record_path) == path_scope(issue_path):
        return 0.08
    return 0.0


def fix_reference_evidence(
    issue: SonarIssue,
    record: SonarIssueRecord,
    files: list[PullRequestFileRecord],
) -> tuple[str, ...]:
    evidence = [
        f"same Sonar rule `{record.rule}`",
        "Sonar marked the historical issue as fixed/resolved",
    ]
    record_path = component_path(record.component)
    if record_path == issue.location.path:
        evidence.append(f"same file `{record_path}`")
    elif path_family(record_path) == path_family(issue.location.path):
        evidence.append(f"same path family `{path_family(record_path)}`")
    elif path_scope(record_path) == path_scope(issue.location.path):
        evidence.append("same code scope (test or production)")
    elif any(file_record.file_path == record_path for file_record in files):
        evidence.append(f"PR touched historical file `{record_path}`")
    if sonar_scoring.code_similarity(issue, record) >= 0.6:
        evidence.append("similar issue text and code context")
    if record.line is not None:
        evidence.append(f"historical issue was near line {record.line}")
    if any(is_analysis_config_path(file_record.file_path) for file_record in files):
        evidence.append("PR also touched analysis configuration, so the match score is lower")
    return tuple(evidence)


def is_analysis_config_path(path: str) -> bool:
    normalized = path.lower()
    filename = normalized.split("/")[-1]
    return (
        filename in {"sonar-project.properties", "pom.xml", "build.gradle", "build.gradle.kts"}
        or normalized.startswith(".github/workflows/")
        or "quality-profile" in normalized
        or "ruleset" in normalized
    )


def pull_request_url(repository_key: str, pr_number: int) -> str:
    return f"https://github.com/{repository_key}/pull/{pr_number}"
