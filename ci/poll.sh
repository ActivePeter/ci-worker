#!/usr/bin/env bash
# poll.sh <owner/repo> <status context> <dispatch event> [only-ref] [target-branches]
# The optional CSV target-branches selects branch heads and open non-fork PRs
# targeting them. Otherwise poll all non-fork PRs and all protected heads.
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

# lines: "<sha> <group>"
if [ -n "$ONLY" ]; then
  if [[ -n "$TARGET_BRANCHES" && ",$TARGET_BRANCHES," != *",$ONLY,"* ]]; then
    echo "::error::$ONLY is outside target branches: $TARGET_BRANCHES" >&2
    exit 2
  fi
  sha=$(get "repos/$REPO/commits/$ONLY" | jq -r .sha)
  work="$sha sha-$sha"
elif [[ -n "$TARGET_BRANCHES" ]]; then
  IFS=, read -r -a targets <<< "$TARGET_BRANCHES"
  work=$(
    for branch in "${targets[@]}"; do
      encoded=$(jq -rn --arg branch "$branch" '$branch | @uri')
      get "repos/$REPO/branches/$encoded" |
        jq -er '"\(.commit.sha) branch-\(.name | gsub("[^A-Za-z0-9._-]"; "_"))"' || exit
      get "repos/$REPO/pulls?state=open&base=$encoded&per_page=100" |
        jq -r --arg r "$REPO" '.[] | select(.head.repo.full_name==$r) | "\(.head.sha) pr-\(.number)"' || exit
    done
  )
  work=$(printf '%s\n' "$work" | sort -u -k1,1)
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
