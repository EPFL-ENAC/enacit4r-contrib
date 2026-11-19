#!/usr/bin/env bash
# Withdraw data from the base branch: run the project command, commit the
# change, and push it. Inputs come from the environment, see action.yml.
set -euo pipefail

: "${TARGET:?TARGET is required}"
: "${BASE:?BASE is required}"
: "${COMMAND:?COMMAND is required}"

# shellcheck source=../ingest/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/../ingest/common.sh"
git_identity

withdraw() {
  echo "Withdraw $TARGET"
  if ! TARGET="$TARGET" bash -c "$COMMAND" </dev/null; then
    echo "::error::The withdraw command failed for $TARGET. Nothing was pushed." >&2
    exit 1
  fi
  git add -A
  if git diff --cached --quiet; then
    echo "::error::nothing to withdraw for $TARGET" >&2
    exit 1
  fi
  local msg=(-m "${COMMIT_PREFIX:-chore(data)}: withdraw $TARGET")
  if [ -n "${REASON:-}" ]; then
    msg+=(-m "$REASON")
  fi
  git commit -q "${msg[@]}"
}

push_with_retry withdraw withdraw
dispatch_deploy
