# Architecture Notes

## Purpose

ContextPR is intended to connect static analysis findings with pull request review workflows.
It fetches SonarQube or SonarCloud pull request issues, selectively enriches them with
case-based historical context, and publishes high-signal inline review comments on GitHub.

The current design intentionally avoids adding text to every issue. ContextPR should add
developer-facing context only when it is likely to reduce ambiguity, support triage, or provide
useful historical evidence beyond the original Sonar message.

## Current codebase

The codebase is organized around a few package boundaries:

- `contextpr.cli` exposes the command line interface.
- `contextpr.config` centralizes environment-backed settings.
- `contextpr.logging_config` sets structured-friendly logging defaults.
- `action.yml` exposes the packaged CLI as a reusable GitHub Action.
- `contextpr.integrations` owns GitHub and SonarQube/SonarCloud API communication.
- `contextpr.enrichment` owns selective issue contextualisation.
- `contextpr.models` contains typed domain objects shared across modules.
- `contextpr.services` orchestrates pull request analysis and comment composition.
- `contextpr.utils` contains small reusable helper functions.

## Request flow

```text
CLI -> configuration -> SonarQube client -> enrichment services -> GitHub client
```

When used through GitHub Actions, the flow becomes:

```text
Workflow -> action.yml -> Docker container -> contextpr analyze
```

The orchestration flow is:

1. Resolve configuration and runtime options.
2. Retrieve pull request issue data from SonarQube or SonarCloud.
3. Optionally synchronize local Sonar, Git, pull request, and review-comment history into the
   SQLite store.
4. Retrieve changed pull request lines from GitHub.
5. Keep only Sonar issues that can be attached to newly changed lines.
6. Retrieve ranked historical Sonar cases from the local repository history store.
7. Build enriched guidance only when the best case reaches the confidence gate.
8. Compose concise review comments.
9. Post or preview inline GitHub review comments.

## Enrichment strategy

ContextPR's production enrichment path is deterministic, case-based, and history-aware:

```text
current Sonar issue -> ranked local Sonar cases -> confidence gate -> evidence-backed comment
```

The implementation prefers concrete historical cases over repository-level aggregate trends. A
historical case contains the Sonar rule, message, file path, line, disposition, similarity score,
confidence score, compact evidence facts, and an optional fix reference.

The confidence gate is intentionally conservative:

```text
confidence < 70% -> no ContextPR enrichment
confidence >= 70% -> compact evidence-backed guidance
confidence >= 90% with a PR-linked fix -> richer precedent template
```

The supported guidance decisions are:

- `likely worth fixing now`
- `safe to defer`
- `review carefully`
- `similar fix available`

Weak history, sparse history, global dataset matches, Git-only matches, PR-only matches, and
review-comment-only matches do not create inline enrichment comments.

Review comments are rendered as short paragraph-separated sections rather than one dense block.
In practice this usually means:

1. the original Sonar message
2. `ContextPR: <decision> · <confidence>% confidence`
3. one compact reason sentence
4. optionally, one closest precedent link or high-confidence PR-linked fix explanation

## Historical context

ContextPR stores several kinds of repository history, but the current inline enrichment decision
source is local Sonar issue history.

The local repository history store can include:

- Sonar project issue history
- repository commit/file-touch history
- merged pull request/file history
- historical GitHub review comments

In v1 of the case-based enrichment flow, Git, pull request, and review-comment records are
supporting evidence only. They may help attribute a resolved Sonar case to a merged pull request
or strengthen confidence for that case, but they cannot independently create an inline enriched
comment.

In GitHub Actions deployments, the SQLite history database can be treated as a rolling cache
rather than a permanent store. A workflow can restore the latest cached `history.db`, run an
incremental sync, save a new immutable cache entry, and then delete older cache versions. This
keeps repeated pull request analyses fast while preserving the design assumption that the
authoritative systems are still Sonar and GitHub.

Historical retrieval scores previous Sonar issues using rule match, message similarity, path
proximity, issue type, severity, tags, lifecycle disposition, recency, and optional fix-reference
evidence. The result is a ranked list of historical cases, not an aggregate trend paragraph.

When local Sonar history contains a resolved issue that can be attributed to a merged pull request,
ContextPR can attach a historical PR reference. That path is intentionally stricter than compact
case guidance: the comment uses the richer PR-linked precedent template only when the historical
fix has at least 90% confidence.

## Dataset artifact

The curated dataset is optional.

- It is not required for repository-local enrichment.
- Its configuration path is retained for backward compatibility.
- The dataset normalization utility remains available for offline experiments.
- It is not loaded by the current `contextpr analyze` enrichment path.

By default, the configuration points to:

```text
dataset/curated_issues_data.xlsx
```

In this repository, `dataset/` is git-ignored, so the dataset is treated as a local experimental
artifact rather than a checked-in project asset.

## Reusable action packaging

The repository is set up so the Python package remains the source of truth and the GitHub
Action acts only as a wrapper around it.

- `action.yml` defines the public inputs exposed to consuming repositories.
- `Dockerfile` packages a stable Python runtime plus the installed `contextpr` package.
- `scripts/action-entrypoint.sh` maps GitHub Action inputs to environment variables and
  invokes the CLI.

This keeps local development and automation aligned. A feature added to the CLI becomes
available to the GitHub Action without duplicating the implementation in a separate codebase.

## Extension points

The implementation leaves room for:

- richer domain models for findings and comments
- additional rule mappings and language-specific pattern tables
- retrieval evaluation and stronger historical ranking
- prompt templates or LLM-assisted rewriting behind strict grounding and abstention
- SonarCloud and self-hosted SonarQube compatibility

## Operational expectations

The repository is configured for:

- Python 3.12+
- editable local development installs
- `pytest` for tests
- `ruff` for linting and formatting
- `mypy` for static type checking
- GitHub Actions CI for validation on push and pull request events
