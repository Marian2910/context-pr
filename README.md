<p align="center">
  <img src="assets/contextpr-logo.png" alt="ContextPR logo" width="180">
</p>

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
4. Enrich issues with repository-local history when available, or fall back to the curated dataset when the repository has little or no history.
5. Generate review-ready comment text.
6. Post inline GitHub pull request comments.

The same Python package can be used in two ways:

- as a local CLI for development and debugging
- as an installable repository add-on with repo-local state
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
contextpr analyze pr 123 --dry-run
contextpr sync-history
contextpr sync
```

You can also invoke the package directly:

```bash
python -m contextpr --help
```

## Installing ContextPR into another repository

ContextPR can be installed as a short CLI command and initialized inside any git repository:

```bash
pipx install git+https://github.com/Marian2910/context-pr.git

cd path/to/your/repository
context-pr init
context-pr sync
context-pr analyze pr 3 --no-dry-run
```

`context-pr init` creates repo-local operational state:

```bash
.context-pr/
  config.toml
  history.db
```

It also prompts for GitHub App credentials and Sonar credentials. The GitHub App ID,
installation ID, repository, and Sonar settings are written to `.env`. If `.env` already exists,
ContextPR updates it in place and preserves existing variables. The GitHub App private key is
copied into:

```bash
secrets/GITHUB_APP_PRIVATE_KEY.pem
```

The setup command automatically adds the local state and secret file to `.gitignore`:

```gitignore
.context-pr/
.env
secrets/
```

It also installs a local pre-commit guard that blocks accidental commits containing `.context-pr/`,
`.env`, or `secrets/`.

Local hooks can be bypassed with `--no-verify`, so use the CLI guard in CI when you want a hard
repository policy:

```yaml
- name: Prevent ContextPR local state from being committed
  run: context-pr guard
```

`context-pr guard` fails if `.context-pr/`, `.env`, or `secrets/` is already tracked by git. If
that happens, remove the files from the index without deleting your local copies:

```bash
git rm -r --cached .context-pr .env secrets
```

In this prototype, repositories that install ContextPR must provide their own GitHub App
credentials locally. A future hosted ContextPR service could keep the official ContextPR GitHub
App private key in a trusted backend or vault and post comments as the shared `ContextPR[bot]`
identity without distributing that private key to users.

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
.context-pr/history.db
```

To populate or refresh that store explicitly:

```bash
contextpr sync
```

When local history is enabled, `contextpr analyze` also refreshes history before composing PR
comments.

The local runtime folder:

```bash
.context-pr/
```

is operational state only. It holds the SQLite history database and should not be committed to
git.

## Dataset fallback mode

ContextPR can also use a curated cross-repository dataset as a fallback when a repository is too
new to have useful local history yet.

This fallback is intended for cold-start situations:

- when local history is disabled
- when local history is enabled but still sparse
- when you want broader comparison examples during early experiments

Dataset-backed comments are worded differently on purpose. They do not claim repository-specific
evidence, and use phrasing such as:

- `In similar issues from other repositories ...`

instead of:

- `In this repository ...`

### Dataset requirement

The dataset is optional, not required for the main local-history workflow.

- If you want only repository-local enrichment, you do not need to provide the dataset file.
- If you want cold-start fallback behavior, provide a dataset file through
  `CONTEXTPR_ISSUE_DATASET_PATH`.

The default configured path is:

```bash
dataset/curated_issues_data.xlsx
```

The `dataset/` directory is ignored by git in this repository, so the file is expected to be
provided locally for experiments rather than stored in version control.

## Comment style

ContextPR does not add text to every Sonar issue. It tries to stay out of the way when Sonar
is already clear, and adds more context only when it has grounded historical evidence.

Depending on the issue and the available history, comments may include:

- the original Sonar message as the opening sentence
- a short follow-up recommendation such as "This looks like a reasonable fix to keep in this PR."
- a historical note about how similar issues were usually handled in this repository, or in other repositories when the dataset fallback is used
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
      actions: write

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Ensure ContextPR state directory exists
        run: mkdir -p .context-pr

      - name: Restore ContextPR history cache
        uses: actions/cache/restore@v4
        with:
          path: .context-pr/history.db
          key: contextpr-history-${{ github.repository }}-v1-${{ github.run_id }}
          restore-keys: |
            contextpr-history-${{ github.repository }}-v1-

      - name: Run ContextPR
        uses: Marian2910/context-pr@main
        env:
          GITHUB_TOKEN: ${{ github.token }}

          CONTEXTPR_ENABLE_LOCAL_HISTORY: "true"
          CONTEXTPR_LOCAL_HISTORY_DB_PATH: ${{ github.workspace }}/.context-pr/history.db

          CONTEXTPR_SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          CONTEXTPR_SONAR_ORGANIZATION: ${{ secrets.SONAR_ORGANIZATION }}
          CONTEXTPR_SONAR_PROJECT_KEY: ${{ secrets.PROJECT_KEY }}
          CONTEXTPR_SONAR_HOST_URL: https://sonarcloud.io

          CONTEXTPR_GITHUB_REPOSITORY: ${{ github.repository }}
          CONTEXTPR_PR_NUMBER: ${{ github.event.pull_request.number }}
          CONTEXTPR_DRY_RUN: "false"

      - name: Save updated ContextPR history cache
        if: always() && hashFiles('.context-pr/history.db') != ''
        uses: actions/cache/save@v4
        with:
          path: .context-pr/history.db
          key: contextpr-history-${{ github.repository }}-v1-${{ github.run_id }}

      - name: Delete older ContextPR caches but keep latest 3
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
          PREFIX: contextpr-history-${{ github.repository }}-v1-
        run: |
          gh api \
            -H "Accept: application/vnd.github+json" \
            "/repos/$REPO/actions/caches?per_page=100" > caches.json

          jq -r --arg prefix "$PREFIX" '
            .actions_caches
            | map(select(.key | startswith($prefix)))
            | sort_by(.last_accessed_at)
            | reverse
            | .[3:]
            | .[].id
          ' caches.json | while read -r cache_id; do
            if [ -n "$cache_id" ]; then
              gh api \
                --method DELETE \
                -H "Accept: application/vnd.github+json" \
                "/repos/$REPO/actions/caches/$cache_id"
            fi
          done
```

The Action wraps `contextpr analyze`. As the Python implementation grows, the GitHub Action
automatically benefits from the same logic because it simply delegates to the packaged CLI.

For GitHub access, the Action uses the workflow token (`github.token`). Consumers only need
to configure Sonar credentials. Review comments will appear from `github-actions[bot]`.

The example above treats the SQLite history database as a rolling cache:

- each run restores the latest available `history.db`
- ContextPR performs an incremental sync against Sonar and GitHub
- the updated database is saved under a new immutable cache key
- older cache entries are deleted, keeping only the latest three

This keeps local-history mode fast without treating the cache as the source of truth. The
authoritative systems remain Sonar and GitHub, and the SQLite database can always be rebuilt.

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
