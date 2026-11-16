#!/usr/bin/env bash
# Legacy default entry for goodputai/dynamo, used while the tested SHA has no
# .github/ci/public-unit.sh: the pure-CPU KVBM shared-host lifecycle checks
# (port of kvbm-shared-pool-lifecycle.yml), split into independent cargo/
# maturin jobs. rust-toolchain.toml in the checkout selects the toolchain.
set -euo pipefail

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
