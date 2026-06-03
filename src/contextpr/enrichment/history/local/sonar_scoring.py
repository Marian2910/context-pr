from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from contextpr.enrichment.history.types import (
    LOCAL_SONAR_SCORE_SCALE,
    RECENCY_DECAY_FLOOR,
    RECENCY_DECAY_TAU_DAYS,
)
from contextpr.enrichment.history.utils import (
    component_path,
    message_overlap,
    parse_timestamp,
    path_family,
    path_scope,
    token_overlap,
)
from contextpr.models import SonarIssue
from contextpr.persistence import SonarIssueRecord


def score_record(issue: SonarIssue, record: SonarIssueRecord) -> float:
    base_similarity = (
        0.45 * rule_similarity(issue, record)
        + 0.35 * code_similarity(issue, record)
        + 0.20 * location_similarity(issue, record)
    )
    score = base_similarity * recency_decay(record) * LOCAL_SONAR_SCORE_SCALE
    score += utility_score(record)
    return round(score, 4)


def rule_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
    if record.rule == issue.rule:
        return 1.0
    issue_tags = set(issue.tags)
    tags = record_tags(record)
    if issue_tags and issue_tags & tags:
        return 0.7
    if (
        record.clean_code_attribute_category
        and record.clean_code_attribute_category == issue.clean_code_attribute_category
    ):
        return 0.7
    if record.clean_code_attribute and record.clean_code_attribute == issue.clean_code_attribute:
        return 0.6
    if record.issue_type == issue.issue_type and issue.issue_type:
        return 0.4
    return 0.0


def code_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
    similarity = message_overlap(issue.message, record.message)
    metadata_similarity = 0.0
    if record.issue_type == issue.issue_type and issue.issue_type:
        metadata_similarity += 0.4
    if record.severity == issue.severity and issue.severity:
        metadata_similarity += 0.2
    if set(issue.tags) & record_tags(record):
        metadata_similarity += 0.2
    if record.clean_code_attribute and record.clean_code_attribute == issue.clean_code_attribute:
        metadata_similarity += 0.1
    if (
        record.clean_code_attribute_category
        and record.clean_code_attribute_category == issue.clean_code_attribute_category
    ):
        metadata_similarity += 0.1
    metadata_similarity = min(metadata_similarity, 1.0)
    return round((0.7 * similarity) + (0.3 * metadata_similarity), 4)


def location_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
    record_path = component_path(record.component)
    issue_path = issue.location.path
    if record_path == issue_path and issue_path:
        return 1.0
    if path_family(record_path) == path_family(issue_path):
        return 0.7
    if path_scope(record_path) == path_scope(issue_path):
        return 0.4
    return 0.2 * token_overlap(issue_path, record_path)


def recency_decay(record: SonarIssueRecord) -> float:
    observed_at = parse_timestamp(record.updated_at) or parse_timestamp(record.created_at)
    if observed_at is None:
        return 1.0
    now = datetime.now(tz=UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - observed_at.astimezone(UTC)).total_seconds() / 86400)
    decay = math.exp(-age_days / RECENCY_DECAY_TAU_DAYS)
    return round(max(RECENCY_DECAY_FLOOR, decay), 4)


def record_tags(record: SonarIssueRecord) -> set[str]:
    if not record.tags_json:
        return set()
    try:
        raw_tags = json.loads(record.tags_json)
    except json.JSONDecodeError:
        return set()
    if not isinstance(raw_tags, list):
        return set()
    return {str(tag) for tag in raw_tags if isinstance(tag, str)}


def utility_score(record: SonarIssueRecord) -> float:
    score = 0.5
    if disposition_bucket(record) is not None:
        score += 1.5
    if record.updated_at:
        score += 0.5
    return score


def disposition_bucket(record: SonarIssueRecord) -> str | None:
    status = (record.status or "").strip().lower()
    resolution = (record.resolution or "").strip().lower()
    if resolution in {"fixed", "resolved", "removed"}:
        return "resolved"
    if resolution in {"wontfix", "won't fix", "false positive", "accepted"}:
        return "accepted"
    if status in {"closed"}:
        return "resolved"
    if status in {"resolved"}:
        return "accepted" if resolution else "resolved"
    if status in {"open", "confirmed", "reopened"}:
        return "persistent"
    return None


def resolution_days(record: SonarIssueRecord) -> float | None:
    if disposition_bucket(record) != "resolved":
        return None
    created_at = parse_timestamp(record.created_at)
    updated_at = parse_timestamp(record.updated_at)
    if created_at is None or updated_at is None or updated_at < created_at:
        return None
    return round((updated_at - created_at).total_seconds() / 86400, 2)


def median_resolution_days(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[middle]
    return round((sorted_values[middle - 1] + sorted_values[middle]) / 2, 2)
