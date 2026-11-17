#!/usr/bin/env bash
# Legacy default entry for goodputai/test (testkit), used while the tested SHA
# has no .github/ci/public-unit.sh. Mirrors test's own ci.yml: static, the
# class-level shards of scripts/ci_shards.py (one worker per core in each
# shard), and its exact-ID audit across shards as the report step.
set -euo pipefail
SHARDS="${TEST_UNIT_SHARDS:-4}"
export TESTKIT_CI=1 PYTHONDONTWRITEBYTECODE=1

case "$1" in
  plan)
    python3 - "$SHARDS" <<'PY'
import json, sys
jobs = [{"id": "static", "timeout": 10, "fetch_depth": 0}]
jobs += [{"id": f"unit-{i}", "timeout": 15} for i in range(int(sys.argv[1]))]
print(json.dumps({"version": 1, "jobs": jobs, "report": True}))
PY
    ;;
  setup)
    if [[ "${TEST_UNIT_SETUP:-legacy}" == nix ]]; then
      python -c 'import sys; assert sys.executable.startswith("/nix/store/"), sys.executable'
      exit 0
    fi
    python3 testkit env prepare --uv uv --cache-config config/cache-ephemeral.json --export-github
    ;;
  run)
    case "$2" in
      static) python scripts/ci.py static ;;
      unit-*)
        index="${2#unit-}"
        PYTHONPATH=scripts python - "$SHARDS" <<'PY'
import sys
from pathlib import Path
import ci_shards
ci_shards.generate(Path('.ci-results/manifest.json'), int(sys.argv[1]))
PY
        cp .ci-results/manifest.json "$CI_OUT/manifest.json"
        python scripts/ci.py unit-shard --workers 0 --shard "$index" --output "$CI_OUT/shard-$index"
        ;;
      *) echo "unknown job $2" >&2; exit 2 ;;
    esac
    ;;
  report)
    mkdir -p .ci-results/shards
    for dir in "$CI_IN"/job-unit-*; do
      index="${dir##*/job-unit-}"
      ln -s "$dir" ".ci-results/shards/unit-shard-$index-attempt-1"
    done
    PYTHONPATH=scripts python3 - <<'PY'
import os
from ci_shards import aggregate_attempts
raise SystemExit(aggregate_attempts('.ci-results/shards', os.environ['CI_OUT'], 1))
PY
    ;;
  *) echo "usage: $0 plan|setup <id>|run <id>|report" >&2; exit 2 ;;
esac
