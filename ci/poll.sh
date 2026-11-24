#!/usr/bin/env bash
# poll.sh <owner/repo> <status context> <dispatch event> [only-ref] [target-branches-csv]
# Queue unit CI for every open non-fork PR head plus the head of every
# protected branch (GitHub branch protection list; no branch names are
# hard-coded here). With target branches specified, poll only their PRs and heads.
# POLL_DRY_RUN=1 prints the selected work without checking or writing statuses.
# Run-once-per-SHA: a SHA that already has any status for
# <context> is skipped. Each dispatch carries a concurrency group (pr-<n> /
# branch-<name>), so a newer head cancels the superseded run.
set -euo pipefail
REPO="$1" CTX="$2" EVENT="$3" ONLY="${4:-}" TARGET_BRANCHES="${5:-}"
DRY_RUN="${POLL_DRY_RUN:-0}"
TOKEN="$(printf %s "$GIE_GIT_TOKEN" | tr -d '[:space:]')"
[ -n "$TOKEN" ] || { echo '::error::GIE_GIT_TOKEN empty'; exit 1; }
[ "$DRY_RUN" = 1 ] || echo "::add-mask::$TOKEN"
API="https://api.github.com"
H1="Authorization: token ${TOKEN}"
H2="Accept: application/vnd.github+json"
get() { curl -fsS -H "$H1" -H "$H2" "$API/$1"; }

allowed_prs() {
  local page=1 body size
  while :; do
    body=$(get "repos/$REPO/pulls?state=open&per_page=100&page=$page") || return
    jq -r --arg r "$REPO" --arg csv "$TARGET_BRANCHES" '
      ($csv | split(",")) as $branches
      | .[]
      | select(.head.repo.full_name == $r and (.base.ref as $base | $branches | index($base)) != null)
      | "\(.head.sha) pr-\(.number) \(.base.ref)"' <<< "$body" || return
    size=$(jq 'length' <<< "$body") || return
    if [ "$size" -lt 100 ]; then
      return
    fi
    page=$((page + 1))
  done
}

allowed_heads() {
  local name endpoint body
  local -a names
  IFS=, read -r -a names <<< "$TARGET_BRANCHES"
  for name in "${names[@]}"; do
    endpoint=$(jq -rn --arg name "$name" '$name | @uri') || return
    body=$(get "repos/$REPO/branches/$endpoint") || return
    jq -er '"\(.commit.sha) branch-\(.name | gsub("[^A-Za-z0-9._-]"; "_")) \(.name)"' <<< "$body" || return
  done
}

# lines: "<sha> <group> [target branch]"
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

if [ "$DRY_RUN" = 1 ]; then
  awk 'NF { print "selected " $0; count++ } END { print "selected=" count+0 }' <<< "$work"
  exit 0
fi

dispatched=0
while read -r ref group target_branch; do
  [ -n "$ref" ] || continue
  if ! body=$(get "repos/$REPO/commits/$ref/status"); then
    echo "skip $ref (status fetch failed)"; continue
  fi
  state=$(printf '%s' "$body" | jq -r --arg ctx "$CTX" \
    '[.statuses[]? | select(.context==$ctx)] | sort_by(.updated_at) | .[-1].state // empty')
  if [ -n "$state" ]; then echo "skip $ref $group (latest=$state)"; continue; fi
  echo "queue $ref $group"
  curl -fsS -X POST -H "$H1" -H "$H2" "$API/repos/$REPO/statuses/$ref" \
    -d "{\"state\":\"pending\",\"context\":\"$CTX\",\"description\":\"queued by poll\"}" >/dev/null \
    || { echo "warn: pending-mark failed for $ref"; continue; }
  curl -fsS -X POST -H "$H1" -H "$H2" "$API/repos/ActivePeter/ci-worker/dispatches" \
    -d "{\"event_type\":\"$EVENT\",\"client_payload\":{\"ref\":\"$ref\",\"group\":\"$group\",\"source\":\"poll\"}}" \
    || { echo "warn: dispatch failed for $ref"; continue; }
  dispatched=$((dispatched+1))
done <<< "$work"
echo "::notice::poll $REPO dispatched=$dispatched"
