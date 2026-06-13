from __future__ import annotations

from dataclasses import dataclass

from contextpr.enrichment.history.local import sonar_fix_refs, sonar_scoring
from contextpr.enrichment.history.types import HistoricalFixReference
from contextpr.enrichment.history.utils import component_path
from contextpr.models import SonarIssue
from contextpr.persistence import HistoryStore, SonarIssueRecord


@dataclass(frozen=True, slots=True)
class FixReferenceResolutionContext:
    store: HistoryStore
    repository_key: str
    issue: SonarIssue
    similar_records: list[SonarIssueRecord]
    top_k: int = 3

class FixReferenceResolver:
    @staticmethod
    def resolve(
            context: FixReferenceResolutionContext,
    ) -> tuple[HistoricalFixReference, ...]:
        return sonar_fix_refs.fix_references(
            store=context.store,
            repository_key=context.repository_key,
            issue=context.issue,
            similar=context.similar_records,
            top_k=context.top_k,
        )

    @staticmethod
    def disposition(record: SonarIssueRecord) -> str | None:
        return sonar_scoring.disposition_bucket(record)

    @staticmethod
    def find_for_record(
        record: SonarIssueRecord,
        fix_references: tuple[HistoricalFixReference, ...],
    ) -> HistoricalFixReference | None:
        return next(
            (
                reference
                for reference in fix_references
                if reference.file_path == component_path(record.component)
            ),
            None,
        )
