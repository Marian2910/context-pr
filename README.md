# ContextPR

ContextPR is a Python tool for enriching SonarQube or SonarCloud pull request findings
with repository-aware historical context and publishing actionable inline feedback on GitHub
pull requests.

The current implementation already supports deterministic comment generation, local history
sync, historical PR-link evidence for resolved issues, a reusable CLI, and a Docker-based
GitHub Action wrapper.

## Architecture at a glance

The package is organized around a few clear concerns:

- `contextpr.cli`: user-facing command line entry points.
- `contextpr.config`: environment-driven configuration loading.
- `contextpr.integrations`: external system clients for GitHub and SonarQube/SonarCloud.
- `contextpr.enrichment`: deterministic issue enrichment, historical retrieval, and message building.
- `contextpr.models`: shared application models.
- `contextpr.services`: pull request analysis and review comment composition.
- `contextpr.utils`: small reusable helper functions.

The current analysis pipeline is:

1. Load runtime configuration.
2. Read Sonar pull request analysis results.
3. Optionally synchronize local Sonar, Git, and GitHub history into a SQLite store.
4. Enrich issues with repository and historical context.
5. Generate review-ready comment text.
6. Post inline GitHub pull request comments.

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
contextpr sync-history
```

You can also invoke the package directly:

```bash
python -m contextpr --help
```

## Local history mode

ContextPR can enrich Sonar findings with repository-local history gathered from:

- historical Sonar project issues
- merged pull requests and touched files
- repository commit history
- historical GitHub review comments

Enable it with:

```bash
export CONTEXTPR_ENABLE_LOCAL_HISTORY=true
```

By default, local history is stored in:

```bash
~/.contextpr/history.db
```

To populate or refresh that store explicitly:

```bash
contextpr sync-history
```

When local history is enabled, `contextpr analyze` also refreshes history before composing PR
comments.

## Comment style

ContextPR does not add text to every Sonar issue. It tries to stay out of the way when Sonar
is already clear, and adds more context only when it has grounded historical evidence.

Depending on the issue and the available history, comments may include:

- the original Sonar message as the opening sentence
- a short follow-up recommendation such as "This looks like a reasonable fix to keep in this PR."
- a historical note about how similar issues were usually handled in this repository
- a linked historical PR when ContextPR can connect a fixed Sonar issue to merged PR file evidence

Rendered comments are intentionally split into short paragraphs to make the guidance easier to
scan in GitHub reviews.

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
        env:
          GITHUB_TOKEN: ${{ github.token }}
```

The Action wraps `contextpr analyze`. As the Python implementation grows, the GitHub Action
automatically benefits from the same logic because it simply delegates to the packaged CLI.

For GitHub access, the Action uses the workflow token (`github.token`). Consumers only need
to configure Sonar credentials. Review comments will appear from `github-actions[bot]`.

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

The repository is still a research-oriented prototype, but it already supports the end-to-end
workflow needed for pull-request review experiments:

- Sonar pull request issue retrieval
- selective historical enrichment
- repository-local history sync
- historical PR-link evidence for fixed issues
- GitHub inline review comment publishing
