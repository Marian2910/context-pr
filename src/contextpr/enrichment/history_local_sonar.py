from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

from contextpr.enrichment.history_constants import MIN_RETRIEVAL_SCORE
from contextpr.enrichment.history_types import (
    FIX_REFERENCE_LOOKBACK_DAYS,
    FIX_REFERENCE_PR_LIMIT,
    FIX_REFERENCE_RECORD_LIMIT,
    LOCAL_SONAR_SCORE_SCALE,
    MAX_FIX_ATTRIBUTION_DELAY_DAYS,
    MIN_FIX_REFERENCE_CONFIDENCE,
    MIN_FIX_REFERENCE_RECORD_SCORE,
    MIN_FIX_REFERENCE_WINDOW_PRS,
    RECENCY_DECAY_FLOOR,
    RECENCY_DECAY_TAU_DAYS,
    HistoricalCaseType,
    HistoricalEvidenceSummary,
    HistoricalFixReference,
    HistoricalIssueCase,
)
from contextpr.enrichment.history_utils import (
    component_path,
    message_overlap,
    parse_timestamp,
    path_family,
    path_scope,
    token_overlap,
)
from contextpr.models import SonarIssue
from contextpr.persistence import (
    HistoryStore,
    PullRequestFileRecord,
    PullRequestRecord,
    SonarIssueRecord,
)


class LocalSonarHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(
        self,
        issue: SonarIssue,
        *,
        top_k: int = 25,
    ) -> HistoricalEvidenceSummary | None:
        stored_issues = self._store.list_sonar_issues(self._repository_key)
        if not stored_issues:
            return None
        scored: list[tuple[SonarIssueRecord, float]] = []
        for record in stored_issues:
            score = self._score_record(issue, record)
            if score >= MIN_RETRIEVAL_SCORE:
                scored.append((record, score))
        if not scored:
            return None
        scored.sort(
            key=lambda item: (item[1], item[0].updated_at or "", item[0].created_at or ""),
            reverse=True,
        )
        evidence = self._summarize_matches(issue, scored[:top_k])
        if not evidence.cases:
            return None
        return evidence

    def _summarize_matches(
        self,
        issue: SonarIssue,
        similar: list[tuple[SonarIssueRecord, float]],
    ) -> HistoricalEvidenceSummary:
        issue_scope = path_scope(issue.location.path)
        issue_family = path_family(issue.location.path)
        issue_path = issue.location.path
        records = [record for record, _score in similar]
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        for record in records:
            record_path = component_path(record.component)
            if path_scope(record_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and path_family(record_path) == issue_family:
                same_path_family_matches += 1
            if record_path == issue_path:
                same_exact_path_matches += 1
        fix_references = self._fix_references(issue, records)
        cases = tuple(
            sorted(
                (
                    self._historical_case(issue, record, score, fix_references)
                    for record, score in similar
                ),
                key=lambda case: (
                    case.confidence,
                    case.fix_reference is not None,
                    case.similarity_score,
                ),
                reverse=True,
            )
        )
        return HistoricalEvidenceSummary(
            source_name="local_sonar",
            cases=cases,
            related_cases_count=len(records),
            close_cases_count=sum(
                1
                for case in cases
                if case.rule == issue.rule
                and (
                    case.file_path == issue_path
                    or (issue_family and path_family(case.file_path) == issue_family)
                )
            ),
            fixed_cases_count=sum(1 for case in cases if case.disposition == "resolved"),
            accepted_cases_count=sum(1 for case in cases if case.disposition == "accepted"),
            persistent_cases_count=sum(1 for case in cases if case.disposition == "persistent"),
        )

    @staticmethod
    def _has_strong_local_signal(evidence: HistoricalEvidenceSummary) -> bool:
        return evidence.best_case() is not None

    def _historical_case(
        self,
        issue: SonarIssue,
        record: SonarIssueRecord,
        score: float,
        fix_references: tuple[HistoricalFixReference, ...],
    ) -> HistoricalIssueCase:
        record_path = component_path(record.component)
        disposition = self._disposition_bucket(record)
        fix_reference = self._fix_reference_for_case(record, fix_references)
        case_type = self._case_type(issue, disposition, fix_reference)
        confidence = self._case_confidence(issue, record, score, disposition, fix_reference)
        return HistoricalIssueCase(
            issue_key=record.issue_key,
            rule=record.rule,
            message=record.message,
            file_path=record_path,
            line=record.line,
            disposition=disposition,
            similarity_score=round(min(score / LOCAL_SONAR_SCORE_SCALE, 1.0), 4),
            confidence=confidence,
            case_type=case_type,
            evidence=self._case_evidence(issue, record, disposition, fix_reference),
            fix_reference=fix_reference,
        )

    @staticmethod
    def _fix_reference_for_case(
        record: SonarIssueRecord,
        fix_references: tuple[HistoricalFixReference, ...],
    ) -> HistoricalFixReference | None:
        record_path = component_path(record.component)
        for reference in fix_references:
            if reference.file_path == record_path:
                return reference
        return None

    @staticmethod
    def _case_type(
        issue: SonarIssue,
        disposition: str | None,
        fix_reference: HistoricalFixReference | None,
    ) -> HistoricalCaseType:
        if issue.issue_type == "BUG":
            return HistoricalCaseType.REVIEW_CAREFULLY
        if disposition == "accepted":
            return HistoricalCaseType.DEFERRED
        if disposition == "persistent":
            return HistoricalCaseType.PERSISTENT
        if disposition == "resolved" or fix_reference is not None:
            return HistoricalCaseType.PREVIOUS_FIX
        return HistoricalCaseType.PERSISTENT

    @staticmethod
    def _case_confidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        score: float,
        disposition: str | None,
        fix_reference: HistoricalFixReference | None,
    ) -> float:
        if fix_reference is not None:
            return fix_reference.confidence
        record_path = component_path(record.component)
        confidence = 0.45 * min(score / LOCAL_SONAR_SCORE_SCALE, 1.0)
        if record.rule == issue.rule:
            confidence += 0.2
        if record_path == issue.location.path:
            confidence += 0.2
        elif path_family(record_path) == path_family(issue.location.path):
            confidence += 0.12
        if disposition in {"resolved", "accepted", "persistent"}:
            confidence += 0.1
        if record.line is not None:
            confidence += 0.05
        return round(min(confidence, 1.0), 2)

    @staticmethod
    def _case_evidence(
        issue: SonarIssue,
        record: SonarIssueRecord,
        disposition: str | None,
        fix_reference: HistoricalFixReference | None,
    ) -> tuple[str, ...]:
        evidence: list[str] = []
        if record.rule == issue.rule:
            evidence.append(f"same rule `{record.rule}`")
        record_path = component_path(record.component)
        if record_path == issue.location.path:
            evidence.append("same file")
        elif path_family(record_path) == path_family(issue.location.path):
            evidence.append("same module")
        if disposition == "resolved":
            evidence.append("historical case was fixed")
        elif disposition == "accepted":
            evidence.append("historical case was accepted/deferred")
        elif disposition == "persistent":
            evidence.append("historical case remained open")
        if fix_reference is not None:
            evidence.append(f"linked to PR #{fix_reference.pr_number}")
        return tuple(evidence)

    @staticmethod
    def _score_record(issue: SonarIssue, record: SonarIssueRecord) -> float:
        base_similarity = (
            0.45 * LocalSonarHistoryRetriever._rule_similarity(issue, record)
            + 0.35 * LocalSonarHistoryRetriever._code_similarity(issue, record)
            + 0.20 * LocalSonarHistoryRetriever._location_similarity(issue, record)
        )
        recency_decay = LocalSonarHistoryRetriever._recency_decay(record)
        score = base_similarity * recency_decay * LOCAL_SONAR_SCORE_SCALE
        score += LocalSonarHistoryRetriever._utility_score(record)
        return round(score, 4)

    @staticmethod
    def _rule_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        if record.rule == issue.rule:
            return 1.0
        issue_tags = set(issue.tags)
        record_tags = LocalSonarHistoryRetriever._record_tags(record)
        if issue_tags and issue_tags & record_tags:
            return 0.7
        if (
            record.clean_code_attribute_category
            and record.clean_code_attribute_category == issue.clean_code_attribute_category
        ):
            return 0.7
        if (
            record.clean_code_attribute
            and record.clean_code_attribute == issue.clean_code_attribute
        ):
            return 0.6
        if record.issue_type == issue.issue_type and issue.issue_type:
            return 0.4
        return 0.0

    @staticmethod
    def _code_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        similarity = message_overlap(issue.message, record.message)
        metadata_similarity = 0.0
        if record.issue_type == issue.issue_type and issue.issue_type:
            metadata_similarity += 0.4
        if record.severity == issue.severity and issue.severity:
            metadata_similarity += 0.2
        if set(issue.tags) & LocalSonarHistoryRetriever._record_tags(record):
            metadata_similarity += 0.2
        if (
            record.clean_code_attribute
            and record.clean_code_attribute == issue.clean_code_attribute
        ):
            metadata_similarity += 0.1
        if (
            record.clean_code_attribute_category
            and record.clean_code_attribute_category == issue.clean_code_attribute_category
        ):
            metadata_similarity += 0.1
        metadata_similarity = min(metadata_similarity, 1.0)
        return round((0.7 * similarity) + (0.3 * metadata_similarity), 4)

    @staticmethod
    def _location_similarity(issue: SonarIssue, record: SonarIssueRecord) -> float:
        record_path = component_path(record.component)
        issue_path = issue.location.path
        if record_path == issue_path and issue_path:
            return 1.0
        if path_family(record_path) == path_family(issue_path):
            return 0.7
        if path_scope(record_path) == path_scope(issue_path):
            return 0.4
        return 0.2 * token_overlap(issue_path, record_path)

    @staticmethod
    def _recency_decay(record: SonarIssueRecord) -> float:
        observed_at = parse_timestamp(record.updated_at) or parse_timestamp(record.created_at)
        if observed_at is None:
            return 1.0
        now = datetime.now(tz=UTC)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        age_days = max(0.0, (now - observed_at.astimezone(UTC)).total_seconds() / 86400)
        decay = math.exp(-age_days / RECENCY_DECAY_TAU_DAYS)
        return round(max(RECENCY_DECAY_FLOOR, decay), 4)

    @staticmethod
    def _record_tags(record: SonarIssueRecord) -> set[str]:
        if not record.tags_json:
            return set()
        try:
            raw_tags = json.loads(record.tags_json)
        except json.JSONDecodeError:
            return set()
        if not isinstance(raw_tags, list):
            return set()
        return {str(tag) for tag in raw_tags if isinstance(tag, str)}

    @staticmethod
    def _utility_score(record: SonarIssueRecord) -> float:
        score = 0.5
        if LocalSonarHistoryRetriever._disposition_bucket(record) is not None:
            score += 1.5
        if record.updated_at:
            score += 0.5
        return score

    @staticmethod
    def _disposition_bucket(record: SonarIssueRecord) -> str | None:
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
        if status in {"accepted", "false-positive", "false_positive"}:
            return "accepted"
        if status in {"open", "confirmed", "reopened"}:
            return "persistent"
        return None

    @staticmethod
    def _resolution_days(record: SonarIssueRecord) -> float | None:
        if LocalSonarHistoryRetriever._disposition_bucket(record) != "resolved":
            return None
        created_at = parse_timestamp(record.created_at)
        updated_at = parse_timestamp(record.updated_at)
        if created_at is None or updated_at is None or updated_at < created_at:
            return None
        return round((updated_at - created_at).total_seconds() / 86400, 2)

    @staticmethod
    def _median_resolution_days(values: list[float]) -> float | None:
        if not values:
            return None
        sorted_values = sorted(values)
        middle = len(sorted_values) // 2
        if len(sorted_values) % 2 == 1:
            return sorted_values[middle]
        return round((sorted_values[middle - 1] + sorted_values[middle]) / 2, 2)

    def _fix_references(
        self, issue: SonarIssue, similar: list[SonarIssueRecord], *, top_k: int = 3
    ) -> tuple[HistoricalFixReference, ...]:
        pull_requests = self._bounded_fix_reference_pull_requests(
            [
                pr
                for pr in self._store.list_pull_requests(self._repository_key)
                if pr.merged_at is not None
            ]
        )
        if not pull_requests:
            return ()
        files_by_pr = {
            pr.pr_number: self._store.list_pull_request_files(self._repository_key, pr.pr_number)
            for pr in pull_requests
        }
        candidate_records = self._fix_reference_candidate_records(issue, similar)
        references: list[HistoricalFixReference] = []
        seen_prs: set[int] = set()
        for record in candidate_records:
            if self._disposition_bucket(record) != "resolved":
                continue
            reference = self._fix_reference_for_record(issue, record, pull_requests, files_by_pr)
            if reference is None or reference.pr_number in seen_prs:
                continue
            references.append(reference)
            seen_prs.add(reference.pr_number)
            if len(references) >= top_k:
                break
        return tuple(references)

    def _fix_reference_candidate_records(
        self, issue: SonarIssue, similar: list[SonarIssueRecord]
    ) -> list[SonarIssueRecord]:
        candidates: dict[str, tuple[SonarIssueRecord, float]] = {
            record.issue_key: (record, 1.0) for record in similar
        }
        for record in self._store.list_sonar_issues(self._repository_key):
            score = self._fix_reference_record_score(issue, record)
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

    @staticmethod
    def _fix_reference_record_score(issue: SonarIssue, record: SonarIssueRecord) -> float:
        if LocalSonarHistoryRetriever._disposition_bucket(record) != "resolved":
            return 0.0
        rule_score = LocalSonarHistoryRetriever._rule_similarity(issue, record)
        location_score = LocalSonarHistoryRetriever._location_similarity(issue, record)
        if rule_score <= 0.0 and location_score <= 0.0:
            return 0.0
        return round((0.6 * rule_score) + (0.4 * location_score), 4)

    def _fix_reference_for_record(
        self,
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
            if not self._pull_request_touches_path(
                files_by_pr.get(pull_request.pr_number, []), record_path
            ):
                continue
            candidates.append((pull_request, int(age.total_seconds())))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[1], -item[0].pr_number))
        pull_request = candidates[0][0]
        files = files_by_pr.get(pull_request.pr_number, [])
        confidence = self._fix_reference_confidence(issue, record, files)
        if confidence < MIN_FIX_REFERENCE_CONFIDENCE:
            return None
        return HistoricalFixReference(
            pr_number=pull_request.pr_number,
            pr_title=pull_request.title,
            pr_url=self._pull_request_url(pull_request.pr_number),
            file_url=f"{self._pull_request_url(pull_request.pr_number)}/files",
            file_path=record_path,
            resolved_at=record.updated_at or "",
            confidence=confidence,
            evidence=self._fix_reference_evidence(issue, record, files),
        )

    @staticmethod
    def _pull_request_touches_path(files: list[PullRequestFileRecord], issue_path: str) -> bool:
        return any(file_record.file_path == issue_path for file_record in files)

    @staticmethod
    def _bounded_fix_reference_pull_requests(
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
            pull_request
            for pull_request, _merged_at in dated_pull_requests[:FIX_REFERENCE_PR_LIMIT]
        ]
        if len(time_window) >= MIN_FIX_REFERENCE_WINDOW_PRS:
            return time_window[:FIX_REFERENCE_PR_LIMIT]
        return count_window

    @staticmethod
    def _fix_reference_confidence(
        issue: SonarIssue, record: SonarIssueRecord, files: list[PullRequestFileRecord]
    ) -> float:
        record_path = component_path(record.component)
        confidence = 0.0
        if record.rule == issue.rule:
            confidence += 0.3
        confidence += LocalSonarHistoryRetriever._location_confidence_bonus(
            issue.location.path, record_path
        )
        if any(file_record.file_path == record_path for file_record in files):
            confidence += 0.2
        confidence += 0.15 * LocalSonarHistoryRetriever._code_similarity(issue, record)
        if record.line is not None:
            confidence += 0.05
        if not any(
            LocalSonarHistoryRetriever._is_analysis_config_path(file_record.file_path)
            for file_record in files
        ):
            confidence += 0.05
        return round(min(confidence, 1.0), 2)

    @staticmethod
    def _location_confidence_bonus(issue_path: str, record_path: str) -> float:
        if record_path == issue_path and issue_path:
            return 0.25
        if path_family(record_path) == path_family(issue_path):
            return 0.16
        if path_scope(record_path) == path_scope(issue_path):
            return 0.08
        return 0.0

    @staticmethod
    def _fix_reference_evidence(
        issue: SonarIssue, record: SonarIssueRecord, files: list[PullRequestFileRecord]
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
        if LocalSonarHistoryRetriever._code_similarity(issue, record) >= 0.6:
            evidence.append("similar issue text and code context")
        if record.line is not None:
            evidence.append(f"historical issue was near line {record.line}")
        if any(
            LocalSonarHistoryRetriever._is_analysis_config_path(file_record.file_path)
            for file_record in files
        ):
            evidence.append("PR also touched analysis configuration, so confidence is lower")
        return tuple(evidence)

    @staticmethod
    def _is_analysis_config_path(path: str) -> bool:
        normalized = path.lower()
        filename = normalized.split("/")[-1]
        return (
            filename in {"sonar-project.properties", "pom.xml", "build.gradle", "build.gradle.kts"}
            or normalized.startswith(".github/workflows/")
            or "quality-profile" in normalized
            or "ruleset" in normalized
        )

    def _pull_request_url(self, pr_number: int) -> str:
        return f"https://github.com/{self._repository_key}/pull/{pr_number}"
