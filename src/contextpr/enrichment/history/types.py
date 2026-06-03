from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True, slots=True)
class IssueContextEvidence:
    sample_size: int
    same_rule_matches: int
    same_scope_matches: int
    same_path_family_matches: int
    strong_match_count: int
    dominant_maintenance: str | None
    dominant_maintenance_share: float
    maintenance_distribution: tuple[tuple[str, int], ...]
    same_exact_path_matches: int = 0
    same_rule_share: float = 0.0
    same_path_family_share: float = 0.0
    same_exact_path_share: float = 0.0
    dominant_disposition: str | None = None
    dominant_disposition_share: float = 0.0
    disposition_distribution: tuple[tuple[str, int], ...] = ()
    salient_terms: tuple[str, ...] = ()
    resolved_share: float = 0.0
    accepted_share: float = 0.0
    persistent_share: float = 0.0
    quick_fix_share: float = 0.0
    median_resolution_days: float | None = None
    fix_references: tuple[HistoricalFixReference, ...] = ()


@dataclass(frozen=True, slots=True)
class CombinedHistoricalContext:
    local_sonar: IssueContextEvidence | None = None
    local_git: IssueContextEvidence | None = None
    local_prs: IssueContextEvidence | None = None
    local_review_comments: IssueContextEvidence | None = None
    global_dataset: IssueContextEvidence | None = None

    def preferred_evidence(self) -> IssueContextEvidence | None:
        source = self.preferred_source_name()
        if source == "local_sonar":
            return self.local_sonar
        if source == "local_git":
            return self.local_git
        if source == "local_prs":
            return self.local_prs
        if source == "local_review_comments":
            return self.local_review_comments
        if source == "global_dataset":
            return self.global_dataset
        return None

    def preferred_source_name(self) -> str | None:
        for source_name, source_evidence in (
            ("local_sonar", self.local_sonar),
            ("local_git", self.local_git),
            ("local_prs", self.local_prs),
            ("local_review_comments", self.local_review_comments),
            ("global_dataset", self.global_dataset),
        ):
            if source_evidence is not None:
                return source_name
        return None


HistoricalContext = IssueContextEvidence

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
