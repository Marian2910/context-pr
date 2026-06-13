from __future__ import annotations

from dataclasses import dataclass

from contextpr.enrichment.history.types import (
    LOCAL_SONAR_SCORE_SCALE,
    HistoricalCaseType,
    HistoricalFixReference,
    HistoricalIssueCase,
)
from contextpr.enrichment.history.utils import component_path, path_family
from contextpr.models import SonarIssue
from contextpr.persistence import SonarIssueRecord


@dataclass(frozen=True, slots=True)
class LocalHistoryCaseInput:
    issue: SonarIssue
    record: SonarIssueRecord
    score: float
    fix_reference: HistoricalFixReference | None
    disposition: str | None


class LocalHistoryCaseBuilder:
    def build(self, build_input: LocalHistoryCaseInput) -> HistoricalIssueCase:
        record = build_input.record
        record_path = component_path(record.component)
        return HistoricalIssueCase(
            issue_key=record.issue_key,
            rule=record.rule,
            message=record.message,
            file_path=record_path,
            line=record.line,
            disposition=build_input.disposition,
            similarity_score=round(min(build_input.score / LOCAL_SONAR_SCORE_SCALE, 1.0), 4),
            match_score=self._match_score(build_input),
            case_type=self._case_type(build_input),
            evidence=self._evidence(build_input),
            fix_reference=build_input.fix_reference,
        )

    @staticmethod
    def _case_type(build_input: LocalHistoryCaseInput) -> HistoricalCaseType:
        issue = build_input.issue
        if issue.issue_type == "BUG":
            return HistoricalCaseType.REVIEW_CAREFULLY
        if build_input.disposition == "accepted":
            return HistoricalCaseType.DEFERRED
        if build_input.disposition == "persistent":
            return HistoricalCaseType.PERSISTENT
        if build_input.disposition == "resolved" or build_input.fix_reference is not None:
            return HistoricalCaseType.PREVIOUS_FIX
        return HistoricalCaseType.PERSISTENT

    @staticmethod
    def _match_score(build_input: LocalHistoryCaseInput) -> float:
        if build_input.fix_reference is not None:
            return build_input.fix_reference.match_score

        issue = build_input.issue
        record = build_input.record
        record_path = component_path(record.component)
        match_score = 0.45 * min(build_input.score / LOCAL_SONAR_SCORE_SCALE, 1.0)
        if record.rule == issue.rule:
            match_score += 0.2
        if record_path == issue.location.path:
            match_score += 0.2
        elif path_family(record_path) == path_family(issue.location.path):
            match_score += 0.12
        if build_input.disposition in {"resolved", "accepted", "persistent"}:
            match_score += 0.1
        if record.line is not None:
            match_score += 0.05
        return round(min(match_score, 1.0), 2)

    @staticmethod
    def _evidence(build_input: LocalHistoryCaseInput) -> tuple[str, ...]:
        issue = build_input.issue
        record = build_input.record
        evidence: list[str] = []
        if record.rule == issue.rule:
            evidence.append(f"same rule `{record.rule}`")
        record_path = component_path(record.component)
        if record_path == issue.location.path:
            evidence.append("same file")
        elif path_family(record_path) == path_family(issue.location.path):
            evidence.append("same module")
        if build_input.disposition == "resolved":
            evidence.append("historical case was fixed")
        elif build_input.disposition == "accepted":
            evidence.append("historical case was accepted/deferred")
        elif build_input.disposition == "persistent":
            evidence.append("historical case remained open")
        if build_input.fix_reference is not None:
            evidence.append(f"linked to PR #{build_input.fix_reference.pr_number}")
        return tuple(evidence)
