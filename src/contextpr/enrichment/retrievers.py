from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from contextpr.enrichment.history import (
    CombinedHistoricalContext,
    GlobalDatasetHistoryRetriever,
    HistoricalContext,
    LocalGitHistoryRetriever,
    LocalPullRequestHistoryRetriever,
    LocalReviewCommentHistoryRetriever,
    LocalSonarHistoryRetriever,
)
from contextpr.enrichment.signals import has_actionable_history
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore


class HistoryRetriever(Protocol):
    def find_context(self, issue: SonarIssue) -> HistoricalContext | None: ...


@dataclass(slots=True)
class HistoryRetrieverSet:
    enable_local_history: bool
    dataset_history_retriever: object | None
    local_history_retriever: object | None
    local_git_history_retriever: object | None
    local_pr_history_retriever: object | None
    local_review_comment_history_retriever: object | None

    @classmethod
    def build(
        cls,
        dataset_path: Path | None = None,
        *,
        enable_local_history: bool = False,
        enable_local_git_history: bool = True,
        history_store: HistoryStore | None = None,
        repository_key: str | None = None,
    ) -> HistoryRetrieverSet:
        return cls(
            enable_local_history=enable_local_history,
            dataset_history_retriever=(
                GlobalDatasetHistoryRetriever(dataset_path)
                if dataset_path is not None
                else None
            ),
            local_history_retriever=build_history_retriever(
                LocalSonarHistoryRetriever,
                enable_local_history=enable_local_history,
                history_store=history_store,
                repository_key=repository_key,
            ),
            local_git_history_retriever=build_history_retriever(
                LocalGitHistoryRetriever,
                enable_local_history=enable_local_history and enable_local_git_history,
                history_store=history_store,
                repository_key=repository_key,
            ),
            local_pr_history_retriever=build_history_retriever(
                LocalPullRequestHistoryRetriever,
                enable_local_history=enable_local_history,
                history_store=history_store,
                repository_key=repository_key,
            ),
            local_review_comment_history_retriever=build_history_retriever(
                LocalReviewCommentHistoryRetriever,
                enable_local_history=enable_local_history,
                history_store=history_store,
                repository_key=repository_key,
            ),
        )

    def historical_context(self, issue: SonarIssue) -> CombinedHistoricalContext:
        global_dataset_context = retrieved_context(
            self.dataset_history_retriever,
            issue,
        )
        if not self.enable_local_history:
            return CombinedHistoricalContext(global_dataset=global_dataset_context)

        return CombinedHistoricalContext(
            local_sonar=retrieved_context(self.local_history_retriever, issue),
            local_git=retrieved_context(self.local_git_history_retriever, issue),
            local_prs=retrieved_context(self.local_pr_history_retriever, issue),
            local_review_comments=retrieved_context(
                self.local_review_comment_history_retriever,
                issue,
            ),
        )

    def requires_configured_local_store(self) -> bool:
        return self.enable_local_history and self.local_history_retriever is None


def retrieved_context(
    retriever: object,
    issue: SonarIssue,
) -> HistoricalContext | None:
    if retriever is None:
        return None

    return actionable_or_none(cast(HistoryRetriever, retriever).find_context(issue))


def active_history(
    historical_context: CombinedHistoricalContext | None,
) -> HistoricalContext | None:
    if historical_context is None:
        return None
    return historical_context.preferred_evidence()


def active_source(historical_context: CombinedHistoricalContext | None) -> str | None:
    if historical_context is None:
        return None
    return historical_context.preferred_source_name()


def actionable_or_none(
    historical_context: HistoricalContext | None,
) -> HistoricalContext | None:
    if not has_actionable_history(historical_context):
        return None
    return historical_context


def build_history_retriever(
    retriever_factory: Callable[[HistoryStore, str], object],
    *,
    enable_local_history: bool,
    history_store: HistoryStore | None,
    repository_key: str | None,
) -> object | None:
    if not enable_local_history or history_store is None or repository_key is None:
        return None
    return retriever_factory(history_store, repository_key)
