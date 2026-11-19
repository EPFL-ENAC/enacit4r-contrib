# Shared by ingest.sh and withdraw.sh: git identity, push with retry, deploy.
# Source this file. It reads BASE, DEPLOY_WORKFLOW, GIT_USER_NAME and
# GIT_USER_EMAIL from the environment.

ATTEMPTS=3

git_identity() {
  git config user.name "${GIT_USER_NAME:-enacit4r-contrib}"
  git config user.email "${GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
}

# push_with_retry STEP VERB: run STEP, then push HEAD to BASE. If the push
# is refused, fetch BASE, reset to it, and run STEP again.
push_with_retry() {
  local attempt
  for attempt in $(seq 1 "$ATTEMPTS"); do
    "$1"
    if git push origin "HEAD:$BASE"; then
      return 0
    fi
    echo "The push to $BASE was refused (attempt $attempt of $ATTEMPTS). Fetch and $2 again."
    git fetch -q origin "$BASE"
    git reset -q --hard "origin/$BASE"
  done
  echo "::error::The push to $BASE was refused $ATTEMPTS times." >&2
  exit 1
}

dispatch_deploy() {
  if [ -n "${DEPLOY_WORKFLOW:-}" ]; then
    gh workflow run "$DEPLOY_WORKFLOW" --ref "$BASE"
    echo "Started $DEPLOY_WORKFLOW on $BASE."
  fi
}
