# Refactoring Architecture Notes

ContextPR keeps stable public import surfaces while moving large implementation modules into
smaller internal modules.

## Persistence

`HistoryStore` remains the public persistence facade. Schema setup, row mapping, and domain
operations are split into private modules under `contextpr.persistence`.

## Enrichment

`IssueEnricher` remains the public enrichment facade. Language profiling, signal calculation,
intent selection, guidance building, and retriever setup live in focused modules under
`contextpr.enrichment`.

## History

Historical context retrieval now lives under `contextpr.enrichment.history`. The package is the
public history surface, while temporary flat compatibility modules such as
`history_local_sonar.py` re-export from the new package layout.

Local Sonar history is split into:

- `history/local/sonar.py` for the retriever facade and summary assembly
- `history/local/sonar_scoring.py` for similarity, disposition, and recency scoring
- `history/local/sonar_fix_refs.py` for historical PR fix-reference attribution

The old private helper methods on `LocalSonarHistoryRetriever` remain as wrappers because tests and
downstream code may still call them during the transition.
