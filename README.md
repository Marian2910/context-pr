# ContextPR

ContextPR is a Python prototype for enriching SonarQube or SonarCloud pull request findings
with historical context and publishing actionable inline feedback on GitHub pull requests.

The current repository contains the initial production-ready scaffold only. It provides a
small reusable package, a CLI entry point, a reusable GitHub Action wrapper, configuration
loading, placeholder integrations, tests, and CI so the business logic can be added
incrementally.

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

The same Python package can be used in two ways:

- as a local CLI for development and debugging
- as a Docker-based GitHub Action that other repositories can call with `uses:`

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

GitHub authentication now uses a GitHub App, not a personal access token. The required GitHub
settings are:

- `CONTEXTPR_GITHUB_APP_ID`
- `CONTEXTPR_GITHUB_INSTALLATION_ID`
- `CONTEXTPR_GITHUB_REPOSITORY`

The private key is read automatically from:

```bash
secrets/GITHUB_APP_PRIVATE_KEY.pem
```

Create that file locally and place the GitHub App PEM contents in it. The `secrets/` directory
is ignored by git, so the key stays local.

Run the CLI:

```bash
contextpr --help
contextpr analyze --pr-number 123 --dry-run
```

You can also invoke the package directly:

```bash
python -m contextpr --help
```

## Using the GitHub Action

This repository also includes a reusable Docker-based GitHub Action in [action.yml](action.yml).
That makes it possible to use ContextPR from other repositories, not just this one.

Example workflow:

```yaml
name: ContextPR

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  contextpr:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Run ContextPR
        uses: Marian2910/context-pr@main
        with:
          sonar-token: ${{ secrets.SONAR_TOKEN }}
          sonar-host-url: https://sonarcloud.io
          sonar-organization: your-organization
          sonar-project-key: your-project-key
          pr-number: ${{ github.event.pull_request.number }}
          github-repository: ${{ github.repository }}
          dry-run: "true"
```

At the moment, the Action wraps the placeholder `contextpr analyze` command. As the Python
implementation grows, the GitHub Action automatically benefits from the same logic because it
simply delegates to the packaged CLI.

To let the GitHub Action authenticate as a bot identity, configure your repository or
organization secrets for the GitHub App and map them to the environment variables expected by
ContextPR. The visible author of review comments will then be the GitHub App bot account
instead of a personal user.

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
