#!/usr/bin/env bash
# poll.sh <owner/repo> <status context> <dispatch event> [only-ref] [target-branches-csv]
# Queue unit CI for every open non-fork PR head plus the head of every
# protected branch (GitHub branch protection list; no branch names are
# hard-coded here). With target branches specified, poll only their PRs and heads.
# Run-once-per-SHA: a SHA that already has any status for
# <context> is skipped. Each dispatch carries a concurrency group (pr-<n> /
# branch-<name>), so a newer head cancels the superseded run.
set -euo pipefail
REPO="$1" CTX="$2" EVENT="$3" ONLY="${4:-}" TARGET_BRANCHES="${5:-}"
TOKEN="$(printf %s "$GIE_GIT_TOKEN" | tr -d '[:space:]')"
[ -n "$TOKEN" ] || { echo '::error::GIE_GIT_TOKEN empty'; exit 1; }
echo "::add-mask::$TOKEN"
API="https://api.github.com"
H1="Authorization: token ${TOKEN}"
H2="Accept: application/vnd.github+json"
get() { curl -fsS -H "$H1" -H "$H2" "$API/$1"; }
retry_description="poll dispatch failed; retry next poll"
mark() {
  local ref=$1 state=$2 description=$3
  curl -fsS -X POST -H "$H1" -H "$H2" "$API/repos/$REPO/statuses/$ref" \
    -d "$(jq -cn --arg state "$state" --arg ctx "$CTX" --arg description "$description" \
      '{state:$state,context:$ctx,description:$description}')" >/dev/null
}

allowed_prs() {
  local page=1 body size
  while :; do
    body=$(get "repos/$REPO/pulls?state=open&per_page=100&page=$page") || return
    jq -r --arg r "$REPO" --arg csv "$TARGET_BRANCHES" '
      ($csv | split(",")) as $branches
      | .[]
      | select(.head.repo.full_name == $r and (.base.ref as $base | $branches | index($base)) != null)
      | "\(.head.sha) pr-\(.number)"' <<< "$body" || return
    size=$(jq 'length' <<< "$body") || return
    if [ "$size" -lt 100 ]; then
      return
    fi
    page=$((page + 1))
  done
}

allowed_heads() {
  local name endpoint response status body
  local -a names
  IFS=, read -r -a names <<< "$TARGET_BRANCHES"
  for name in "${names[@]}"; do
    endpoint=$(jq -rn --arg name "$name" '$name | @uri') || return
    response=$(curl -sS -w $'\n%{http_code}' -H "$H1" -H "$H2" "$API/repos/$REPO/branches/$endpoint") || return
    status=${response##*$'\n'}
    body=${response%$'\n'*}
    case "$status" in
      200) ;;
      404) echo "::warning::target branch $name was not found" >&2; continue ;;
      *) echo "::error::branch $name lookup returned HTTP $status" >&2; return 1 ;;
    esac
    jq -er '"\(.commit.sha) branch-\(.name | gsub("[^A-Za-z0-9._-]"; "_"))"' <<< "$body" || return
  done
}

# lines: "<sha> <group>"
if [ -n "$TARGET_BRANCHES" ]; then
  prs=$(allowed_prs)
  branches=$(allowed_heads)
  work=$(printf '%s\n%s\n' "$branches" "$prs" | awk 'NF' | sort -u -k1,1)
  if [ -n "$ONLY" ]; then
    encoded_ref=$(jq -rn --arg ref "$ONLY" '$ref | @uri')
    sha=$(get "repos/$REPO/commits/$encoded_ref" | jq -er .sha)
    work=$(awk -v sha="$sha" '$1 == sha' <<< "$work")
    if [ -z "$work" ]; then
      echo "::error::ref $ONLY is not a PR head or branch head for $TARGET_BRANCHES" >&2
      exit 1
    fi
  fi
elif [ -n "$ONLY" ]; then
  sha=$(get "repos/$REPO/commits/$ONLY" | jq -r .sha)
  work="$sha sha-$sha"
else
  prs=$(get "repos/$REPO/pulls?state=open&per_page=100" |
    jq -r --arg r "$REPO" '.[] | select(.head.repo.full_name==$r) | "\(.head.sha) pr-\(.number)"')
  branches=$(get "repos/$REPO/branches?protected=true&per_page=100" |
    jq -r '.[] | "\(.commit.sha) branch-\(.name | gsub("[^A-Za-z0-9._-]"; "_"))"')
  [ -n "$branches" ] || echo "::warning::$REPO has no protected branch; only PR heads are polled"
  work=$(printf '%s\n%s\n' "$prs" "$branches" | awk 'NF' | sort -u -k1,1)
fi

dispatched=0
while read -r ref group; do
  [ -n "$ref" ] || continue
  if ! body=$(get "repos/$REPO/commits/$ref/status"); then
    echo "skip $ref (status fetch failed)"; continue
  fi
  latest=$(jq -c --arg ctx "$CTX" '
    [.statuses[]? | select(.context==$ctx)] | sort_by(.updated_at) | .[-1] // {}' <<< "$body")
  state=$(jq -r '.state // empty' <<< "$latest")
  description=$(jq -r '.description // empty' <<< "$latest")
  if [ -n "$state" ] && { [ "$state" != failure ] || [ "$description" != "$retry_description" ]; }; then
    echo "skip $ref $group (latest=$state)"
    continue
  fi
  echo "queue $ref $group"
  dispatch_payload="{\"event_type\":\"$EVENT\",\"client_payload\":{\"ref\":\"$ref\",\"group\":\"$group\",\"source\":\"poll\"}}"
  mark "$ref" pending "queued by poll" || { echo "warn: pending-mark failed for $ref"; continue; }
  if ! curl -fsS -X POST -H "$H1" -H "$H2" "$API/repos/ActivePeter/ci-worker/dispatches" \
        -d "$dispatch_payload"; then
    echo "warn: dispatch failed for $ref"
    mark "$ref" failure "$retry_description" || {
      echo "::error::dispatch failure could not be recorded for $ref" >&2
      exit 1
    }
    continue
  fi
  dispatched=$((dispatched+1))
done <<< "$work"
echo "::notice::poll $REPO dispatched=$dispatched"
