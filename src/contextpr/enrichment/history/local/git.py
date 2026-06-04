from __future__ import annotations

from contextpr.enrichment.history.types import IssueContextEvidence
from contextpr.enrichment.history.utils import distribution, dominant_share, path_family, path_scope, salient_terms, share
from contextpr.models import SonarIssue
from contextpr.persistence import GitCommitRecord, GitFileTouchRecord, HistoryStore, SonarIssueRecord


class LocalGitHistoryRetriever:
    def __init__(self, store: HistoryStore, repository_key: str) -> None:
        self._store = store
        self._repository_key = repository_key
        self._commits: list[GitCommitRecord] | None = None
        self._touches: list[GitFileTouchRecord] | None = None
        self._sonar_issues: list[SonarIssueRecord] | None = None

    def find_context(self, issue: SonarIssue, *, top_k: int = 25) -> IssueContextEvidence | None:
        commits = self._list_git_commits()
        if not commits:
            return None
        touches = self._list_git_file_touches()
        touches_by_commit: dict[str, list[GitFileTouchRecord]] = {}
        for touch in touches:
            touches_by_commit.setdefault(touch.commit_sha, []).append(touch)
        scored: list[tuple[GitCommitRecord, list[GitFileTouchRecord], float]] = []
        for commit in commits:
            commit_touches = touches_by_commit.get(commit.commit_sha, [])
            if not commit_touches:
                continue
            score = self._score_commit(issue, commit_touches)
            if score >= 1.0:
                scored.append((commit, commit_touches, score))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[2], item[0].authored_at, item[0].commit_sha), reverse=True)
        relevant = scored[:top_k]
        evidence = self._summarize_matches(issue, relevant)
        if not self._has_strong_git_signal(evidence):
            return None
        return evidence

    def _summarize_matches(self, issue: SonarIssue, relevant: list[tuple[GitCommitRecord, list[GitFileTouchRecord], float]]) -> IssueContextEvidence:
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        issue_scope = path_scope(issue_path)
        same_scope_matches = 0
        same_path_family_matches = 0
        same_exact_path_matches = 0
        strong_match_count = 0
        for _commit, touches, score in relevant:
            exact = any(touch.file_path == issue_path for touch in touches)
            family = any(issue_family and touch.module_family == issue_family for touch in touches)
            scope = any(path_scope(touch.file_path) == issue_scope for touch in touches)
            if scope:
                same_scope_matches += 1
            if family:
                same_path_family_matches += 1
            if exact:
                same_exact_path_matches += 1
            if score >= 3.0:
                strong_match_count += 1
        maintenance_buckets = [self._maintenance_bucket_from_commit(commit.classification) for commit, _touches, _score in relevant]
        maintenance_distribution = distribution(maintenance_buckets)
        dominant_maintenance, dominant_maintenance_share = dominant_share(maintenance_distribution, sample_size=len(relevant))
        sonar_issues = self._list_sonar_issues()
        same_rule_history = [
            record for record in sonar_issues if record.rule == issue.rule and self._rule_history_is_relevant(issue, record.component)
        ]
        same_rule_matches = min(len(same_rule_history), len(relevant))
        issue_salient_terms = salient_terms(
            issue,
            [f"{commit.message} " + " ".join(touch.file_path for touch in touches) for commit, touches, _score in relevant],
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
    def _score_commit(issue: SonarIssue, touches: list[GitFileTouchRecord]) -> float:
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        issue_scope = path_scope(issue_path)
        score = 0.0
        if any(touch.file_path == issue_path for touch in touches):
            score += 3.5
        if issue_family and any(touch.module_family == issue_family for touch in touches):
            score += 2.5
        if any(path_scope(touch.file_path) == issue_scope for touch in touches):
            score += 1.0
        unique_paths = {touch.file_path for touch in touches}
        score += max(0.0, min(1.5, len(unique_paths) * 0.25))
        return score

    @staticmethod
    def _has_strong_git_signal(evidence: IssueContextEvidence) -> bool:
        if evidence.sample_size < 2:
            return False
        if evidence.same_exact_path_matches >= 2:
            return True
        return evidence.same_path_family_matches >= 3 and evidence.same_path_family_share >= 0.6

    @staticmethod
    def _maintenance_bucket_from_commit(classification: str) -> str:
        normalized = classification.strip().lower()
        if normalized == "fix":
            return "behavior"
        if normalized in {"test", "docs", "build"}:
            return "supporting"
        return "cleanup"

    @staticmethod
    def _rule_history_is_relevant(issue: SonarIssue, component: str) -> bool:
        from contextpr.enrichment.history.utils import component_path

        record_path = component_path(component)
        issue_path = issue.location.path
        issue_family = path_family(issue_path)
        return record_path == issue_path or (bool(issue_family) and path_family(record_path) == issue_family)

    def _list_git_commits(self) -> list[GitCommitRecord]:
        if self._commits is None:
            self._commits = self._store.list_git_commits(self._repository_key)
        return self._commits

    def _list_git_file_touches(self) -> list[GitFileTouchRecord]:
        if self._touches is None:
            self._touches = self._store.list_git_file_touches(self._repository_key)
        return self._touches

    def _list_sonar_issues(self) -> list[SonarIssueRecord]:
        if self._sonar_issues is None:
            self._sonar_issues = self._store.list_sonar_issues(self._repository_key)
        return self._sonar_issues
