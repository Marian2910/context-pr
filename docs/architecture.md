# Architecture Notes

## Goal

ContextPR connects Sonar pull request findings with GitHub review comments.

The project is designed to stay deterministic and easy to explain:

- Sonar findings are the source input.
- GitHub is the review output.
- Local repository history is the main evidence source.
- Cross-project dataset evidence is only a fallback.

## Main flow

```text
CLI -> config -> optional history sync -> GitHub diff retrieval -> SonarQube issues -> enrichment -> review composer -> GitHub publishing
```

For one pull request, the runtime flow is:

1. load configuration
2. optionally sync local history into SQLite
3. get changed PR files and lines from GitHub
4. fetch Sonar issues for the PR
5. retrieve similar historical cases
6. keep only strong matches for historical enrichment
7. compose inline review comments
8. post comments to GitHub

## Code layout

- `contextpr.cli`: command-line package
- `contextpr.config`: environment-backed settings
- `contextpr.integrations.github`: GitHub API client
- `contextpr.integrations.sonarqube`: SonarQube/SonarCloud client
- `contextpr.enrichment`: historical retrieval and guidance building
- `contextpr.persistence`: SQLite history store
- `contextpr.services`: orchestration and comment composition

## Enrichment strategy

ContextPR does not try to explain every Sonar issue.

It adds extra context only when a historical case is strong enough to be useful. The important
idea is:

```text
current issue -> similar historical cases -> match-score gate -> enriched guidance or plain Sonar message
```

The project currently uses:

- local Sonar issue history as the primary signal
- historical PR/file evidence as supporting evidence
- dataset matches only when local history does not return usable context

Typical guidance output is compact:

1. original Sonar message
2. decision
3. historical match score
4. one short reason
5. optionally, a precedent PR link

## Persistence

The local history store is SQLite-based and keeps:

- Sonar issue history
- Sonar issue observations
- Git commit history
- Git file touches
- pull requests
- pull request files
- pull request review comments
- sync checkpoints

This store is operational state, not source-of-truth business data. Sonar and GitHub remain the
authoritative systems.

## GitHub workflow

The repository currently keeps the suggested GitHub Actions workflow in [../action.yml](../action.yml).

That workflow:

- restores the local history cache
- runs ContextPR
- saves the updated cache
- cleans older cache entries

## Design trade-offs

The project intentionally prefers:

- explicit Python code over heavy abstractions
- deterministic heuristics over opaque generation
- silence over weak review comments
- repository-local evidence over generic fallback guidance

That trade-off makes the system easier to inspect, debug, and defend in a dissertation context.
