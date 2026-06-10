<p align="center">
  <img src="assets/contextpr-logo.png" alt="ContextPR logo" width="180">
</p>

# ContextPR

ContextPR is a Python prototype that reads SonarQube or SonarCloud pull request findings,
enriches them with repository history, and posts inline review comments on GitHub.

The current implementation is intentionally deterministic:

- Sonar findings are the input.
- Local repository history is the primary evidence source.
- A curated dataset can be used only as a fallback.
- Comments are posted only when the historical match is strong enough.

## What it does

For a pull request, ContextPR can:

1. fetch Sonar issues for the PR
2. sync repository-local Sonar, PR, review, and commit history into SQLite
3. rank similar historical cases
4. generate compact review comments
5. publish those comments on GitHub

## Project structure

- `src/contextpr/cli`: command-line entrypoints
- `src/contextpr/config.py`: environment-based configuration
- `src/contextpr/integrations`: GitHub and SonarQube clients
- `src/contextpr/enrichment`: historical retrieval and guidance generation
- `src/contextpr/persistence`: SQLite history store
- `src/contextpr/services`: PR analysis and comment composition

See [docs/architecture.md](docs/architecture.md) for the short architecture note.

## Local setup

Create a virtual environment and install the project:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Required configuration

ContextPR now uses only GitHub App authentication.

Environment variables:

- `CONTEXTPR_GITHUB_APP_ID`
- `CONTEXTPR_GITHUB_INSTALLATION_ID`
- `CONTEXTPR_GITHUB_REPOSITORY`
- `CONTEXTPR_SONAR_TOKEN`
- `CONTEXTPR_SONAR_PROJECT_KEY`

Optional:

- `CONTEXTPR_SONAR_ORGANIZATION`
- `CONTEXTPR_SONAR_HOST_URL`
- `CONTEXTPR_ENABLE_LOCAL_HISTORY`
- `CONTEXTPR_LOCAL_HISTORY_DB_PATH`
- `CONTEXTPR_ISSUE_DATASET_PATH`

The GitHub App private key is read from:

```text
secrets/GITHUB_APP_PRIVATE_KEY.pem
```

## CLI usage

Main commands:

```bash
contextpr --help
contextpr analyze --pr-number 123 --dry-run
contextpr analyze --pr-number 123 --no-dry-run
contextpr sync
contextpr sync-history
```

You can also run it as a module:

```bash
PYTHONPATH=src .venv/bin/python -m contextpr --help
```

## Repository-local mode

ContextPR can be initialized inside another git repository:

```bash
pipx install git+https://github.com/Marian2910/context-pr.git

cd path/to/repository
mkdir -p secrets
# place the GitHub App PEM here:
# secrets/GITHUB_APP_PRIVATE_KEY.pem

context-pr init
context-pr sync
context-pr analyze pr 11 --no-dry-run
```

`context-pr init` creates:

```text
.context-pr/
  config.toml
  history.db
```

It also updates `.gitignore` and can install a local pre-commit guard to avoid committing:

- `.context-pr/`
- `.env`
- `secrets/`

## GitHub workflow

This repository currently keeps the suggested GitHub Actions workflow in
[action.yml](action.yml).

That file shows the expected automation setup:

- checkout the repository
- restore `.context-pr/history.db` from cache
- run ContextPR with GitHub App and Sonar secrets
- save the updated history cache
- prune older cache entries

If you use the workflow example, make sure these secrets exist in the target repository:

- `CONTEXTPR_GITHUB_APP_ID`
- `CONTEXTPR_GITHUB_INSTALLATION_ID`
- `SONAR_TOKEN`
- `SONAR_ORGANIZATION`
- `PROJECT_KEY`

## Comment behavior

ContextPR does not comment on every Sonar issue.

It only emits enriched comments when the best historical case passes the match-score threshold.
The usual output shape is:

```text
<Sonar issue message>

ContextPR: <decision> · <match-score>% historical match score
Reason: <short explanation>
```

For stronger historical evidence, ContextPR can also include a linked precedent PR.

## Development

Common commands:

```bash
make install
make lint
make typecheck
make test
make ci
```

## Status

This is still a research-oriented prototype built for dissertation work, but the end-to-end
flow is working:

- Sonar PR issue retrieval
- local history sync
- history-backed enrichment
- GitHub inline review comment publishing
