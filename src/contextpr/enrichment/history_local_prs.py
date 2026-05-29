from __future__ import annotations

from contextpr.enrichment.history_local_git import LocalGitHistoryRetriever
from contextpr.enrichment.history_types import IssueContextEvidence
from contextpr.enrichment.history_utils import distribution, dominant_share, path_family, path_scope, salient_terms, share
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore, PullRequestFileRecord, PullRequestRecord


class LocalPullRequestHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        pull_requests = self._store.list_pull_requests(self._repository_key)
        if not pull_requests:
            return None
        files_by_pr = {
            pull_request.pr_number: self._store.list_pull_request_files(self._repository_key, pull_request.pr_number)
            for pull_request in pull_requests
        }
        scored: list[tuple[PullRequestRecord, list[PullRequestFileRecord], float]] = []
        for pull_request in pull_requests:
            files = files_by_pr.get(pull_request.pr_number, [])
            if not files:
                continue
            score = self._score_pull_request(issue, files)
            if score >= 1.0:
                scored.append((pull_request, files, score))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[2], item[0].updated_at or "", item[0].pr_number), reverse=True)
        relevant = scored[:top_k]
        evidence = self._summarize_matches(issue, relevant)
        if not self._has_strong_signal(evidence):
            return None
        return evidence

    def _summarize_matches(self, issue: SonarIssue, relevant: list[tuple[PullRequestRecord, list[PullRequestFileRecord], float]]) -> IssueContextEvidence:
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        issue_scope = path_scope(issue_path)
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        strong_match_count = 0
        maintenance_buckets: list[str] = []
        for pull_request, files, score in relevant:
            exact = any(file_record.file_path == issue_path for file_record in files)
            family = any(issue_family and path_family(file_record.file_path) == issue_family for file_record in files)
            scope = any(path_scope(file_record.file_path) == issue_scope for file_record in files)
            if scope:
                same_scope_matches += 1
            if family:
                same_path_family_matches += 1
            if exact:
                same_exact_path_matches += 1
            if score >= 3.0:
                strong_match_count += 1
            maintenance_buckets.append(self._maintenance_bucket_from_text(f"{pull_request.title}\n{pull_request.body or ''}"))
        maintenance_distribution = distribution(maintenance_buckets)
        dominant_maintenance, dominant_maintenance_share = dominant_share(maintenance_distribution, sample_size=len(relevant))
        same_rule_history = [
            record
            for record in self._store.list_sonar_issues(self._repository_key)
            if record.rule == issue.rule and LocalGitHistoryRetriever._rule_history_is_relevant(issue, record.component)
        ]
        same_rule_matches = min(max(len(same_rule_history), same_exact_path_matches), len(relevant))
        issue_salient_terms = salient_terms(
            issue,
            [f"{pull_request.title} {pull_request.body or ''} " + " ".join(file_record.file_path for file_record in files) for pull_request, files, _score in relevant],
        )
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
    def _score_pull_request(issue: SonarIssue, files: list[PullRequestFileRecord]) -> float:
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        issue_scope = path_scope(issue_path)
        score = 0.0
        if any(file_record.file_path == issue_path for file_record in files):
            score += 3.5
        if issue_family and any(path_family(file_record.file_path) == issue_family for file_record in files):
            score += 2.0
        if any(path_scope(file_record.file_path) == issue_scope for file_record in files):
            score += 1.0
        return score

    @staticmethod
    def _has_strong_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        if evidence.same_exact_path_matches >= 2:
            return True
        return evidence.same_path_family_matches >= 3 and evidence.same_path_family_share >= 0.6

    @staticmethod
    def _maintenance_bucket_from_text(text: str) -> str:
        normalized = text.lower()
        if any(token in normalized for token in ("fix", "bug", "hotfix", "behavior")):
            return "behavior"
        if any(token in normalized for token in ("test", "docs", "readme", "workflow", "ci", "build")):
            return "supporting"
        return "cleanup"
