#!/bin/sh
set -eu

input_value() {
  underscored_name="$1"
  hyphenated_name="$2"
  default_value="${3:-}"

  value="$(printenv "$underscored_name" 2>/dev/null || true)"
  if [ -z "$value" ]; then
    value="$(printenv "$hyphenated_name" 2>/dev/null || true)"
  fi
  if [ -n "$value" ]; then
    printf '%s' "$value"
    return
  fi
  printf '%s' "$default_value"
}

INPUT_GITHUB_TOKEN_VALUE="$(input_value INPUT_GITHUB_TOKEN INPUT_GITHUB-TOKEN "${CONTEXTPR_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}")"
INPUT_GITHUB_API_URL_VALUE="$(input_value INPUT_GITHUB_API_URL INPUT_GITHUB-API-URL "${CONTEXTPR_GITHUB_API_URL:-https://api.github.com}")"
INPUT_GITHUB_REPOSITORY_VALUE="$(input_value INPUT_GITHUB_REPOSITORY INPUT_GITHUB-REPOSITORY "${CONTEXTPR_GITHUB_REPOSITORY:-${GITHUB_REPOSITORY:-}}")"
INPUT_SONAR_TOKEN_VALUE="$(input_value INPUT_SONAR_TOKEN INPUT_SONAR-TOKEN "${CONTEXTPR_SONAR_TOKEN:-}")"
INPUT_SONAR_HOST_URL_VALUE="$(input_value INPUT_SONAR_HOST_URL INPUT_SONAR-HOST-URL "${CONTEXTPR_SONAR_HOST_URL:-https://sonarcloud.io}")"
INPUT_SONAR_ORGANIZATION_VALUE="$(input_value INPUT_SONAR_ORGANIZATION INPUT_SONAR-ORGANIZATION "${CONTEXTPR_SONAR_ORGANIZATION:-}")"
INPUT_SONAR_PROJECT_KEY_VALUE="$(input_value INPUT_SONAR_PROJECT_KEY INPUT_SONAR-PROJECT-KEY "${CONTEXTPR_SONAR_PROJECT_KEY:-}")"
INPUT_LOG_LEVEL_VALUE="$(input_value INPUT_LOG_LEVEL INPUT_LOG-LEVEL "${CONTEXTPR_LOG_LEVEL:-INFO}")"
INPUT_PR_NUMBER_VALUE="$(input_value INPUT_PR_NUMBER INPUT_PR-NUMBER "${CONTEXTPR_PR_NUMBER:-}")"
INPUT_DRY_RUN_VALUE="$(input_value INPUT_DRY_RUN INPUT_DRY-RUN "${CONTEXTPR_DRY_RUN:-true}")"

export CONTEXTPR_GITHUB_TOKEN="$INPUT_GITHUB_TOKEN_VALUE"
export CONTEXTPR_GITHUB_API_URL="$INPUT_GITHUB_API_URL_VALUE"
export CONTEXTPR_GITHUB_REPOSITORY="$INPUT_GITHUB_REPOSITORY_VALUE"
export CONTEXTPR_SONAR_TOKEN="$INPUT_SONAR_TOKEN_VALUE"
export CONTEXTPR_SONAR_HOST_URL="$INPUT_SONAR_HOST_URL_VALUE"
export CONTEXTPR_SONAR_ORGANIZATION="$INPUT_SONAR_ORGANIZATION_VALUE"
export CONTEXTPR_SONAR_PROJECT_KEY="$INPUT_SONAR_PROJECT_KEY_VALUE"
export CONTEXTPR_LOG_LEVEL="$INPUT_LOG_LEVEL_VALUE"

set -- contextpr analyze

if [ -n "$INPUT_PR_NUMBER_VALUE" ]; then
  set -- "$@" --pr-number "$INPUT_PR_NUMBER_VALUE"
fi

case "$INPUT_DRY_RUN_VALUE" in
  true|TRUE|True|1|yes|YES|Yes)
    set -- "$@" --dry-run
    ;;
  false|FALSE|False|0|no|NO|No)
    set -- "$@" --no-dry-run
    ;;
  *)
    echo "Invalid dry-run value: $INPUT_DRY_RUN_VALUE" >&2
    exit 2
    ;;
esac

exec "$@"
