from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from contextpr.data import TARGET_COLUMN, load_dataset_file
from contextpr.enrichment.history.types import (
    HistoricalCaseType,
    HistoricalEvidenceSummary,
    HistoricalIssueCase,
)
from contextpr.enrichment.history.utils import token_overlap
from contextpr.models import SonarIssue

MIN_DATASET_SCORE = 0.55
MAX_DATASET_CONFIDENCE = 0.82


@dataclass(frozen=True, slots=True)
class DatasetMatch:
    row_index: int
    score: float
    case_type: HistoricalCaseType
    classification: str
    component: str


class DatasetHistoryRetriever:
    def __init__(self, dataset_path: Path) -> None:
        self._dataset = load_dataset_file(dataset_path)

    def find_context(self, issue: SonarIssue) -> HistoricalEvidenceSummary | None:
        matches: list[DatasetMatch] = []
        for row_index, row in self._dataset.iterrows():
            classification = str(row[TARGET_COLUMN]).strip().lower()
            case_type = _classification_case_type(classification)
            if case_type is None:
                continue

            score = _match_score(issue, row)
            if score < MIN_DATASET_SCORE:
                continue

            matches.append(
                DatasetMatch(
                    row_index=row_index,
                    score=score,
                    case_type=case_type,
                    classification=classification,
                    component=str(row["component"]).strip(),
                )
            )

        if not matches:
            return None

        matches.sort(key=lambda item: item.score, reverse=True)
        top_matches = matches[:5]
        cases = tuple(_build_case(issue, match) for match in top_matches)
        return HistoricalEvidenceSummary(
            source_name="dataset",
            cases=cases,
            related_cases_count=len(matches),
            close_cases_count=len(top_matches),
            fixed_cases_count=sum(
                1 for match in top_matches if match.case_type is HistoricalCaseType.PREVIOUS_FIX
            ),
            accepted_cases_count=sum(
                1 for match in top_matches if match.case_type is HistoricalCaseType.DEFERRED
            ),
            persistent_cases_count=sum(
                1 for match in top_matches if match.case_type is HistoricalCaseType.PERSISTENT
            ),
        )


def _build_case(issue: SonarIssue, match: DatasetMatch) -> HistoricalIssueCase:
    confidence = round(min(match.score, MAX_DATASET_CONFIDENCE), 2)
    evidence = (
        "fallback signal from curated cross-project issue history",
        f"dataset classification `{match.classification}`",
    )
    if match.component:
        evidence += (f"matched dataset component `{match.component}`",)
    return HistoricalIssueCase(
        issue_key=f"dataset:{match.row_index}",
        rule=issue.rule,
        message=issue.message,
        file_path=issue.location.path,
        line=issue.location.line,
        disposition=match.classification,
        similarity_score=match.score,
        confidence=confidence,
        case_type=match.case_type,
        evidence=evidence,
        fix_reference=None,
    )


def _classification_case_type(classification: str) -> HistoricalCaseType | None:
    normalized = classification.strip().lower()
    if normalized in {"fix", "fixed", "actionable", "true_positive"}:
        return HistoricalCaseType.PREVIOUS_FIX
    if normalized in {"defer", "accepted", "accept", "false_positive", "wontfix", "won't fix"}:
        return HistoricalCaseType.DEFERRED
    if normalized in {"persistent", "open"}:
        return HistoricalCaseType.PERSISTENT
    if normalized in {"review", "manual_review", "manual-review"}:
        return HistoricalCaseType.REVIEW_CAREFULLY
    return None


def _match_score(issue: SonarIssue, row: object) -> float:
    score = 0.0
    if str(row["rule"]) == issue.rule:
        score += 0.4

    row_message = str(row["message"])
    if row_message == issue.message:
        score += 0.2
    else:
        score += 0.2 * token_overlap(issue.message, row_message)

    if str(row["type"]) == issue.issue_type:
        score += 0.1
    if str(row["severity"]) == issue.severity:
        score += 0.08
    if str(row["clean_code_attribute"]) == issue.clean_code_attribute:
        score += 0.07
    if str(row["clean_code_attribute_category"]) == issue.clean_code_attribute_category:
        score += 0.05

    issue_extension = Path(issue.location.path).suffix.lower() or "no_extension"
    if str(row["file_extension"]) == issue_extension:
        score += 0.05

    issue_tags = set(issue.tags)
    row_tags = {str(tag) for tag in row["tags"]}
    if issue_tags and row_tags:
        score += 0.05 * (len(issue_tags & row_tags) / len(issue_tags | row_tags))

    return round(min(score, 1.0), 2)
