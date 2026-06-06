from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class HistoricalFixReference:
    pr_number: int
    pr_title: str
    pr_url: str
    file_url: str | None
    file_path: str
    resolved_at: str
    confidence: float
    evidence: tuple[str, ...]


class HistoricalCaseType(StrEnum):
    PREVIOUS_FIX = "previous_fix"
    DEFERRED = "deferred"
    PERSISTENT = "persistent"
    REVIEW_CAREFULLY = "review_carefully"


@dataclass(frozen=True, slots=True)
class HistoricalIssueCase:
    issue_key: str
    rule: str
    message: str
    file_path: str
    line: int | None
    disposition: str | None
    similarity_score: float
    confidence: float
    case_type: HistoricalCaseType
    evidence: tuple[str, ...]
    fix_reference: HistoricalFixReference | None = None


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceSummary:
    source_name: str
    cases: tuple[HistoricalIssueCase, ...]
    related_cases_count: int
    close_cases_count: int
    fixed_cases_count: int
    accepted_cases_count: int
    persistent_cases_count: int

    def best_case(self) -> HistoricalIssueCase | None:
        if not self.cases:
            return None
        return self.cases[0]


@dataclass(frozen=True, slots=True)
class EvidenceBackedGuidance:
    decision: str
    confidence: float
    reason: str
    case_type: HistoricalCaseType
    case_key: str
    precedent_url: str | None = None
    precedent_pr_number: int | None = None
    precedent_evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CombinedHistoricalContext:
    local_sonar: HistoricalEvidenceSummary | None = None
    dataset: HistoricalEvidenceSummary | None = None

    def preferred_evidence(self) -> HistoricalEvidenceSummary | None:
        return self.local_sonar or self.dataset

    def preferred_source_name(self) -> str | None:
        if self.local_sonar is not None:
            return "local_sonar"
        if self.dataset is not None:
            return "dataset"
        return None


FIX_REFERENCE_LOOKBACK_DAYS = 365
FIX_REFERENCE_PR_LIMIT = 500
MIN_FIX_REFERENCE_WINDOW_PRS = 3
MAX_FIX_ATTRIBUTION_DELAY_DAYS = 14
RECENCY_DECAY_TAU_DAYS = 180.0
RECENCY_DECAY_FLOOR = 0.35
LOCAL_SONAR_SCORE_SCALE = 20.0
FIX_REFERENCE_RECORD_LIMIT = 100
MIN_FIX_REFERENCE_RECORD_SCORE = 0.6
MIN_FIX_REFERENCE_CONFIDENCE = 0.7
