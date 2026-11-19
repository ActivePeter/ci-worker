#!/usr/bin/env bash
# poll.sh <owner/repo> <status context> <dispatch event> [only-ref]
# Queue unit CI for every open non-fork PR head plus the head of every
# protected branch (GitHub branch protection list; no branch names are
# hard-coded here). Run-once-per-SHA: a SHA that already has any status for
# <context> is skipped. Each dispatch carries a concurrency group (pr-<n> /
# branch-<name>), so a newer head cancels the superseded run.
set -euo pipefail
REPO="$1" CTX="$2" EVENT="$3" ONLY="${4:-}"
TOKEN="$(printf %s "$GIE_GIT_TOKEN" | tr -d '[:space:]')"
[ -n "$TOKEN" ] || { echo '::error::GIE_GIT_TOKEN empty'; exit 1; }
echo "::add-mask::$TOKEN"
API="https://api.github.com"
H1="Authorization: token ${TOKEN}"
H2="Accept: application/vnd.github+json"
get() { curl -fsS -H "$H1" -H "$H2" "$API/$1"; }

# lines: "<sha> <group> [<pinned PR base SHA>]"
if [ -n "$ONLY" ]; then
  sha=$(get "repos/$REPO/commits/$ONLY" | jq -r .sha)
  work="$sha sha-$sha"
else
  prs=$(get "repos/$REPO/pulls?state=open&per_page=100" |
    jq -r --arg r "$REPO" '.[] | select(.head.repo.full_name==$r) | "\(.head.sha) pr-\(.number) \(.base.sha // "")"')
  branches=$(get "repos/$REPO/branches?protected=true&per_page=100" |
    jq -r '.[] | "\(.commit.sha) branch-\(.name | gsub("[^A-Za-z0-9._-]"; "_"))"')
  [ -n "$branches" ] || echo "::warning::$REPO has no protected branch; only PR heads are polled"
  # A shared SHA must run the full plan if it is a protected branch or
  # belongs to more than one PR base.
  work=$(printf '%s\n%s\n' "$prs" "$branches" | awk '
    NF >= 2 {
      if (!($1 in group) || $2 ~ /^branch-/) {group[$1]=$2; base[$1]=$3}
      else if ($3 != base[$1]) base[$1]=""
    }
    END {for (sha in group) print sha, group[sha], base[sha]}
  ' | sort)
fi

dispatched=0
while read -r ref group base; do
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
    -d "{\"event_type\":\"$EVENT\",\"client_payload\":{\"ref\":\"$ref\",\"group\":\"$group\",\"source\":\"poll\",\"base\":\"${base:-}\"}}" \
    || { echo "warn: dispatch failed for $ref"; continue; }
  dispatched=$((dispatched+1))
done <<< "$work"
echo "::notice::poll $REPO dispatched=$dispatched"
