# Architecture Notes

## Purpose

ContextPR is intended to connect static analysis findings with pull request review workflows.
It fetches SonarQube or SonarCloud pull request issues, selectively enriches them with
rule-based and historical context, and publishes high-signal inline review comments on GitHub.

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
6. Look up historical context from the local repository history store first and fall back to the
   curated issue dataset only when repository history is unavailable or too sparse.
7. Decide whether the issue should receive no, minimal, contextual, or detailed enrichment.
8. Compose concise review comments.
9. Post or preview inline GitHub review comments.

## Enrichment strategy

ContextPR's production enrichment path is currently deterministic and history-aware:

```text
Sonar rule -> issue pattern -> guidance level -> optional historical note -> PR comment
```

The implementation prefers stable Sonar rule identifiers over message text. Known Python rules
are mapped directly to issue patterns, for example:

```text
python:S1481 -> unused_local_variable
python:S1172 -> unused_function_parameter
python:S1192 -> duplicated_literal
python:S1186 -> empty_function
python:S3923 -> duplicate_condition_branches
```

Message text is used only as a fallback for unknown or unmapped rules.

Each issue receives one of four guidance levels:

- `none`: add no ContextPR text because Sonar is already self-explanatory or history is weak.
- `minimal`: add only a short historical note.
- `contextual`: add a short triage-oriented sentence plus historical evidence.
- `detailed`: add a short explanation, next step, and optional historical evidence.

This keeps simple warnings, such as unused local variables, from receiving redundant paraphrases
of the Sonar message.

Review comments are rendered as short paragraph-separated sections rather than one dense block.
In practice this usually means:

1. the original Sonar message
2. a short explanation or follow-up recommendation when warranted
3. a historical note when the evidence is grounded enough

## Historical context

ContextPR uses two history sources, with a clear preference order:

- the local repository history store populated through `contextpr sync-history`
- the curated dataset used as a cold-start fallback when local history is not yet useful

Local repository history can include:

- Sonar project issue history
- repository commit/file-touch history
- merged pull request/file history
- historical GitHub review comments

The dataset fallback is intentionally narrower in product meaning:

- it helps ContextPR say something sensible for fresh repositories
- it does not justify `In this repository ...` wording
- it is best treated as comparative background rather than project-specific evidence

In other words, local history is the primary evidence source, and the dataset is a fallback for
early-stage or low-history repositories.

In GitHub Actions deployments, the SQLite history database can be treated as a rolling cache
rather than a permanent store. A workflow can restore the latest cached `history.db`, run an
incremental sync, save a new immutable cache entry, and then delete older cache versions. This
keeps repeated pull request analyses fast while preserving the design assumption that the
authoritative systems are still Sonar and GitHub.

Historical retrieval scores previous issues using rule, type, clean-code metadata, severity,
file extension, tags, and message overlap. Historical notes are shown only when the evidence is
grounded enough:

- at least five similar issues are retrieved
- at least one retrieved issue has the same Sonar rule
- the most common label covers at least half of retrieved examples
- at least two retrieved examples are strong matches

The wording is confidence-aware. Small samples use cautious phrasing such as "in a small set of
similar cases". Stronger evidence can use "often" or "usually". When the historical distribution
is close across buckets, ContextPR reports mixed history instead of forcing a single conclusion.

When local Sonar history contains a resolved issue that can be attributed to a merged pull request,
ContextPR can also attach a historical PR reference. That path is intentionally stricter than
generic similarity notes: it requires merged PR evidence and touched-file support before a link is
shown in the final GitHub comment.

## Dataset artifact

The curated dataset is optional.

- It is not required when ContextPR is used with repository-local history.
- It is required only if you want the cross-repository fallback behavior.

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
