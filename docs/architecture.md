# Architecture Notes

## Purpose

ContextPR is intended to connect static analysis findings with pull request review workflows.
The long-term goal is to fetch SonarQube or SonarCloud pull request issues, enrich them with
historical repository context, and publish high-signal inline review comments on GitHub.

## Current codebase

The current codebase establishes the development infrastructure and package boundaries:

- `contextpr.cli` exposes the command line interface.
- `contextpr.config` centralizes environment-backed settings.
- `contextpr.logging_config` sets structured-friendly logging defaults.
- `action.yml` exposes the packaged CLI as a reusable GitHub Action.
- `contextpr.integrations` will own external API communication.
- `contextpr.enrichment` will own historical retrieval and NLP-assisted explanation logic.
- `contextpr.models` contains typed domain objects shared across modules.
- `contextpr.utils` is reserved for small reusable helper functions.

## Planned request flow

```text
CLI -> configuration -> SonarQube client -> enrichment services -> GitHub client
```

When used through GitHub Actions, the flow becomes:

```text
Workflow -> action.yml -> Docker container -> contextpr analyze
```

A likely future orchestration flow is:

1. Resolve configuration and runtime options.
2. Retrieve pull request issue data from SonarQube or SonarCloud.
3. Look up historical context from previous issues, files, or pull requests.
4. Compose concise review comments.
5. Post or preview inline GitHub review comments.

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

The scaffold is intentionally small, but it leaves room for:

- a service layer to orchestrate end-to-end analysis runs
- richer domain models for findings and comments
- persistence for cached historical context
- prompt templates or NLP adapters for summarization
- GitHub App authentication or token-based access
- SonarCloud and self-hosted SonarQube compatibility

## Operational expectations

The repository is configured for:

- Python 3.12+
- editable local development installs
- `pytest` for tests
- `ruff` for linting and formatting
- `mypy` for static type checking
- GitHub Actions CI for validation on push and pull request events
