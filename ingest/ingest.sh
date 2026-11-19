#!/usr/bin/env bash
# Fold the submissions of a merged contribution pull request into the
# data, one commit per submission, and push the result to the base branch.
# Inputs come from the environment, see action.yml.
set -euo pipefail

: "${PR_NUMBER:?PR_NUMBER is required}"
: "${BASE:?BASE is required}"
: "${COMMAND:?COMMAND is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
FOLDER="${FOLDER:-submissions}"
FOLDER="${FOLDER%/}"
ATTEMPTS=3

git config user.name "${GIT_USER_NAME:-enacit4r-contrib}"
git config user.email "${GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

files=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER/files" --paginate --jq '.[].filename')

# The distinct <folder>/<id> prefixes of the pull request files.
candidates=$(printf '%s\n' "$files" | while IFS= read -r f; do
  rest="${f#"$FOLDER"/}"
  if [ "$rest" != "$f" ] && [ "${rest#*/}" != "$rest" ]; then
    printf '%s/%s\n' "$FOLDER" "${rest%%/*}"
  fi
done | sort -u)

# The candidates that exist in the working tree.
existing() {
  printf '%s\n' "$candidates" | while IFS= read -r sub; do
    if [ -n "$sub" ] && [ -d "$sub" ]; then printf '%s\n' "$sub"; fi
  done
}

ingest() {
  local sub
  while IFS= read -r sub; do
    echo "Ingest $sub"
    if ! SUBMISSION="$sub" bash -c "$COMMAND" </dev/null; then
      echo "::error::The ingest command failed for $sub. Nothing was pushed." >&2
      exit 1
    fi
    git add -A
    if git diff --cached --quiet; then
      echo "No change for $sub. No commit."
    else
      git commit -q -m "${COMMIT_PREFIX:-chore(data)}: ingest $sub (#$PR_NUMBER)"
    fi
  done <<<"$1"
}

pushed=""
for attempt in $(seq 1 "$ATTEMPTS"); do
  subs=$(existing)
  if [ -z "$subs" ]; then
    echo "Pull request #$PR_NUMBER has no submission under $FOLDER/ in the working tree. Nothing to ingest."
    exit 0
  fi
  ingest "$subs"
  if git push origin "HEAD:$BASE"; then
    pushed=1
    break
  fi
  echo "The push to $BASE was refused (attempt $attempt of $ATTEMPTS). Fetch and ingest again."
  git fetch -q origin "$BASE"
  git reset -q --hard "origin/$BASE"
done

if [ -z "$pushed" ]; then
  echo "::error::The push to $BASE was refused $ATTEMPTS times." >&2
  exit 1
fi

if [ -n "${DEPLOY_WORKFLOW:-}" ]; then
  gh workflow run "$DEPLOY_WORKFLOW" --ref "$BASE"
  echo "Started $DEPLOY_WORKFLOW on $BASE."
fi
