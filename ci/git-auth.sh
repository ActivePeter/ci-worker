#!/usr/bin/env bash
# Job-local read access to every private github.com/goodputai/* repository
# (Cargo/pip/git deps included) through GIE_GIT_TOKEN. Prefix insteadOf, so a
# lockfile may reference any goodputai repo without per-branch special cases.
set -euo pipefail
TOKEN="$(printf %s "${GIE_GIT_TOKEN:-}" | tr -d '[:space:]')"
[ -n "$TOKEN" ] || { echo '::error::GIE_GIT_TOKEN empty'; exit 1; }
echo "::add-mask::$TOKEN"
url="https://x-access-token:${TOKEN}@github.com/goodputai/"
git config --global --replace-all "url.${url}.insteadOf" "https://github.com/goodputai/"
git config --global --add "url.${url}.insteadOf" "ssh://git@github.com/goodputai/"
git config --global --add "url.${url}.insteadOf" "git@github.com:goodputai/"
if [ -n "${GITHUB_ENV:-}" ]; then echo 'CARGO_NET_GIT_FETCH_WITH_CLI=true' >> "$GITHUB_ENV"; fi
