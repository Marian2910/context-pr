from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from contextpr.enrichment.history import (
    CombinedHistoricalContext,
    EvidenceBackedGuidance,
    HistoricalCaseType,
    HistoricalEvidenceSummary,
    HistoricalIssueCase,
)
from contextpr.models import SonarIssue

MIN_ENRICHMENT_MATCH_SCORE = 0.70


class GuidanceLevel(StrEnum):
    NONE = "none"
    CONTEXTUAL = "contextual"


@dataclass(frozen=True, slots=True)
class DeveloperGuidance:
    level: GuidanceLevel
    evidence: EvidenceBackedGuidance


@dataclass(frozen=True, slots=True)
class IssueEnrichment:
    guidance: DeveloperGuidance
    historical_context: CombinedHistoricalContext | None


@dataclass(frozen=True, slots=True)
class GuidanceBuildInput:
    issue: SonarIssue
    summary: HistoricalEvidenceSummary
    case: HistoricalIssueCase


class GuidanceBuilder:
    def build(
        self,
        issue: SonarIssue,
        historical_context: CombinedHistoricalContext,
    ) -> DeveloperGuidance | None:
        summary = historical_context.preferred_evidence()
        if summary is None:
            return None

        case = summary.best_case()
        if case is None or case.match_score < MIN_ENRICHMENT_MATCH_SCORE:
            return None

        build_input = GuidanceBuildInput(
            issue=issue,
            summary=summary,
            case=case,
        )
        evidence = EvidenceBackedGuidance(
            decision=self._decision(build_input),
            match_score=case.match_score,
            reason=self._reason(build_input),
            case_type=case.case_type,
            case_key=case.issue_key,
            precedent_url=self._precedent_url(case),
            precedent_pr_number=case.fix_reference.pr_number if case.fix_reference else None,
            precedent_evidence=case.fix_reference.evidence if case.fix_reference else (),
        )
        return DeveloperGuidance(level=GuidanceLevel.CONTEXTUAL, evidence=evidence)

    def _decision(self, build_input: GuidanceBuildInput) -> str:
        issue = build_input.issue
        case = build_input.case
        if self._requires_security_review(issue):
            return "requires security review"
        if case.case_type in {HistoricalCaseType.DEFERRED, HistoricalCaseType.PERSISTENT}:
            return "safe to defer"
        if case.case_type is HistoricalCaseType.REVIEW_CAREFULLY:
            return "review carefully"
        return "likely worth fixing now"

    @staticmethod
    def _requires_security_review(issue: SonarIssue) -> bool:
        issue_type = issue.issue_type.strip().upper()
        if issue_type in {"VULNERABILITY", "SECURITY_HOTSPOT", "SECURITY", "HOTSPOT"}:
            return True
        return issue.rule.lower().startswith(
            ("pythonsecurity:", "javasecurity:", "javascriptsecurity:")
        )

    @staticmethod
    def _precedent_url(case: HistoricalIssueCase) -> str | None:
        if case.fix_reference is None:
            return None
        return case.fix_reference.file_url or case.fix_reference.pr_url

    def _reason(self, build_input: GuidanceBuildInput) -> str:
        issue = build_input.issue
        summary = build_input.summary
        case = build_input.case
        file_suffix = self._file_suffix(issue, summary)
        history_scope = (
            "cross-project dataset history"
            if summary.source_name == "dataset"
            else "repository history"
        )
        singular_history_scope = (
            "cross-project dataset precedent"
            if summary.source_name == "dataset"
            else "historical precedent"
        )
        if case.case_type is HistoricalCaseType.DEFERRED:
            if self._requires_security_review(issue):
                return (
                    f"{history_scope.capitalize()} for `{issue.rule}` shows accepted or open "
                    "cases, but this security-sensitive finding "
                    f"still needs manual review{file_suffix}."
                )
            return (
                f"{history_scope.capitalize()} for `{issue.rule}` includes accepted or open "
                f"cases{file_suffix}."
            )
        if case.case_type is HistoricalCaseType.PERSISTENT:
            if self._requires_security_review(issue):
                return (
                    f"{history_scope.capitalize()} for `{issue.rule}` includes open cases, but "
                    "this security-sensitive finding "
                    f"still needs manual review{file_suffix}."
                )
            return (
                f"{history_scope.capitalize()} for `{issue.rule}` includes similar open cases"
                f"{file_suffix}."
            )
        if case.case_type is HistoricalCaseType.REVIEW_CAREFULLY:
            return (
                f"the closest same-rule {singular_history_scope} for `{issue.rule}` "
                f"needs extra review{file_suffix}."
            )
        return (
            f"{history_scope.capitalize()} for `{issue.rule}` includes similar cases that were "
            f"fixed{file_suffix}."
        )

    @staticmethod
    def _file_suffix(issue: SonarIssue, summary: HistoricalEvidenceSummary) -> str:
        if any(case.file_path == issue.location.path for case in summary.cases):
            return ", including one in this file"
        return ""
