#!/bin/sh
set -eu

export CONTEXTPR_GITHUB_TOKEN="${INPUT_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"
export CONTEXTPR_GITHUB_API_URL="${INPUT_GITHUB_API_URL:-https://api.github.com}"
export CONTEXTPR_GITHUB_REPOSITORY="${INPUT_GITHUB_REPOSITORY:-${GITHUB_REPOSITORY:-}}"
export CONTEXTPR_SONAR_TOKEN="${INPUT_SONAR_TOKEN:-}"
export CONTEXTPR_SONAR_HOST_URL="${INPUT_SONAR_HOST_URL:-https://sonarcloud.io}"
export CONTEXTPR_SONAR_ORGANIZATION="${INPUT_SONAR_ORGANIZATION:-}"
export CONTEXTPR_SONAR_PROJECT_KEY="${INPUT_SONAR_PROJECT_KEY:-}"
export CONTEXTPR_LOG_LEVEL="${INPUT_LOG_LEVEL:-INFO}"

set -- contextpr analyze

if [ -n "${INPUT_PR_NUMBER:-}" ]; then
  set -- "$@" --pr-number "${INPUT_PR_NUMBER}"
fi

case "${INPUT_DRY_RUN:-true}" in
  true|TRUE|True|1|yes|YES|Yes)
    set -- "$@" --dry-run
    ;;
  false|FALSE|False|0|no|NO|No)
    set -- "$@" --no-dry-run
    ;;
  *)
    echo "Invalid dry-run value: ${INPUT_DRY_RUN:-}" >&2
    exit 2
    ;;
esac

exec "$@"
