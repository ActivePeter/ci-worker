#!/usr/bin/env bash
# Bridge the checkout's input-admission and LLM contracts when declared.
set -euo pipefail

if [[ -f .github/workflows/release-1.6.1-contracts.yml ]]; then
  exec /usr/bin/python3 -I "$(dirname "$0")/../workflow.py" dynamo "$@"
fi

# Preserve the existing KVBM entry for the release 1.4 workflow.
if [[ ! -f .github/workflows/pre-merge-release-1.4.0.yml && ! -f .github/workflows/kvbm-shared-pool-lifecycle.yml ]]; then
  printf '该提交无桥接对象：%s（缺少 Dynamo contracts workflow）\n' "${CI_REF_SHA:-$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" >&2
  exit 1
fi

case "$1" in
  plan)
    cat <<'JSON'
{"version": 1, "report": false, "jobs": [
  {"id": "rcommu", "timeout": 20, "rust_cache": true},
  {"id": "kvbm-lib", "timeout": 25, "rust_cache": true},
  {"id": "kvbm-ipc", "timeout": 25, "rust_cache": true},
  {"id": "python", "timeout": 25, "rust_cache": true, "python": "3.12"}
]}
JSON
    ;;
  setup)
    sudo apt-get update -qq && sudo apt-get install -y -qq libclang-dev
    ;;
  run)
    case "$2" in
      rcommu) cargo test --locked -p rcommu-lite ;;
      kvbm-lib)
        cargo test --locked -p kvbm-host --lib -- --test-threads=1
        cargo test --locked -p kvbm-host --doc
        ;;
      kvbm-ipc)
        cargo test --locked --release -p kvbm-host --test confirm_ipc -- --test-threads=1
        cargo test --locked --release -p kvbm-host --test multiprocess -- --test-threads=1
        ;;
      python)
        python3 -m pip install 'maturin>=1.8,<2' pytest pytest-timeout
        python3 -m maturin build --locked --manifest-path lib/kvbm-host/Cargo.toml --out "$RUNNER_TEMP/wheels"
        python3 -m pip install --no-deps "$RUNNER_TEMP"/wheels/dynamo_hicache-*.whl
        python3 -m dynamo_hicache config
        python3 -c 'from dynamo_hicache import _native; assert len(_native.page_key(list(range(16)))) == 16'
        python3 -m pytest -v lib/kvbm-host/tests/test_sharing.py lib/kvbm-host/tests/test_numa.py
        ;;
      *) echo "unknown job $2" >&2; exit 2 ;;
    esac
    ;;
  *) echo "usage: $0 plan|setup <id>|run <id>|report" >&2; exit 2 ;;
esac
