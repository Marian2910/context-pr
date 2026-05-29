from __future__ import annotations

from contextpr.enrichment.history_local_git import LocalGitHistoryRetriever
from contextpr.enrichment.history_types import IssueContextEvidence
from contextpr.enrichment.history_utils import distribution, dominant_share, message_overlap, path_family, path_scope, salient_terms, share
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore, PullRequestReviewCommentRecord


class LocalReviewCommentHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        comments = self._store.list_all_pull_request_review_comments(self._repository_key)
        if not comments:
            return None
        scored: list[tuple[PullRequestReviewCommentRecord, float]] = []
        for comment in comments:
            score = self._score_comment(issue, comment)
            if score >= 1.0:
                scored.append((comment, score))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[1], item[0].updated_at or "", item[0].comment_id), reverse=True)
        relevant = [comment for comment, _score in scored[:top_k]]
        evidence = self._summarize_matches(issue, relevant)
        if not self._has_strong_signal(evidence):
            return None
        return evidence

    def _summarize_matches(self, issue: SonarIssue, relevant: list[PullRequestReviewCommentRecord]) -> IssueContextEvidence:
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        issue_scope = path_scope(issue_path)
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        strong_match_count = 0
        maintenance_buckets: list[str] = []
        for comment in relevant:
            file_path = comment.file_path or ""
            if path_scope(file_path) == issue_scope:
                same_scope_matches += 1
            if issue_family and path_family(file_path) == issue_family:
                same_path_family_matches += 1
            if file_path == issue_path:
                same_exact_path_matches += 1
                strong_match_count += 1
            maintenance_buckets.append(self._maintenance_bucket_from_text(comment.body))
        maintenance_distribution = distribution(maintenance_buckets)
        dominant_maintenance, dominant_maintenance_share = dominant_share(maintenance_distribution, sample_size=len(relevant))
        same_rule_history = [
            record
            for record in self._store.list_sonar_issues(self._repository_key)
            if record.rule == issue.rule and LocalGitHistoryRetriever._rule_history_is_relevant(issue, record.component)
        ]
        same_rule_matches = min(max(len(same_rule_history), same_exact_path_matches), len(relevant))
        issue_salient_terms = salient_terms(issue, [f"{comment.body} {comment.file_path or ''}" for comment in relevant])
        return IssueContextEvidence(
            sample_size=len(relevant),
            same_rule_matches=same_rule_matches,
            same_scope_matches=same_scope_matches,
            same_path_family_matches=same_path_family_matches,
            same_exact_path_matches=same_exact_path_matches,
            strong_match_count=strong_match_count,
            dominant_maintenance=dominant_maintenance,
            dominant_maintenance_share=dominant_maintenance_share,
            maintenance_distribution=maintenance_distribution,
            same_rule_share=share(same_rule_matches, len(relevant)),
            same_path_family_share=share(same_path_family_matches, len(relevant)),
            same_exact_path_share=share(same_exact_path_matches, len(relevant)),
            salient_terms=issue_salient_terms,
        )

    @staticmethod
    def _score_comment(issue: SonarIssue, comment: PullRequestReviewCommentRecord) -> float:
        file_path = comment.file_path or ""
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        score = 0.0
        if file_path == issue_path:
            score += 3.0
        if issue_family and path_family(file_path) == issue_family:
            score += 1.5
        score += 2.0 * message_overlap(issue.message, comment.body)
        if issue.rule.lower() in comment.body.lower():
            score += 1.5
        return score

    @staticmethod
    def _has_strong_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        return evidence.same_exact_path_matches >= 2

    @staticmethod
    def _maintenance_bucket_from_text(text: str) -> str:
        normalized = text.lower()
        if any(token in normalized for token in ("behavior", "semantic", "correctness", "break")):
            return "behavior"
        if any(token in normalized for token in ("test", "docs", "comment", "naming")):
            return "supporting"
        return "cleanup"
