# ContextPR

ContextPR is a Python prototype for enriching SonarQube or SonarCloud pull request findings
with historical context and publishing actionable inline feedback on GitHub pull requests.

The current repository contains the initial production-ready scaffold only. It provides a
small reusable package, a CLI entry point, configuration loading, placeholder integrations,
tests, and CI so the business logic can be added incrementally.

## Architecture at a glance

The package is organized around a few clear concerns:

- `contextpr.cli`: user-facing command line entry points.
- `contextpr.config`: environment-driven configuration loading.
- `contextpr.integrations`: external system clients for GitHub and SonarQube/SonarCloud.
- `contextpr.enrichment`: future historical and NLP-based enrichment services.
- `contextpr.models`: shared application models.
- `contextpr.utils`: small reusable helper functions.

The expected future pipeline is:

1. Load runtime configuration.
2. Read Sonar pull request analysis results.
3. Enrich issues with repository and historical context.
4. Generate review-ready comment text.
5. Post inline GitHub pull request comments.

## Getting started

Create and activate a virtual environment, then install the project in editable mode:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copy the example environment file and adjust values for your environment:

```bash
cp .env.example .env
```

Run the CLI:

```bash
contextpr --help
contextpr analyze --pr-number 123 --dry-run
```

You can also invoke the package directly:

```bash
python -m contextpr --help
```

## Development workflow

Common commands are available through `make`:

```bash
make install
make lint
make typecheck
make test
make ci
```

## Status

This repository is intentionally minimal at this stage. It is a scaffold for a future system
that will provide contextual SonarQube feedback in pull requests, not a full implementation
of the GitHub or Sonar APIs yet.
