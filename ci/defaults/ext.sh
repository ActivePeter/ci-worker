#!/usr/bin/env bash
# Legacy default entry for goodputai/goodput-infer-ext, used while the tested
# SHA has no .github/ci/public-unit.sh: ext ci.yml's `unit` job split into the
# python side (CPU engine env, unit/wiring/harness tests, maturin bindings) and
# the cargo side (fmt/test/clippy of every workspace and native case).
set -euo pipefail
pin() { python3 e2e/harness/ci.py env --format github | sed -n "s/^$1=//p"; }

case "$1" in
  plan)
    printf '{"version":1,"report":false,"jobs":[{"id":"python","timeout":30,"python":"%s"},{"id":"cargo","timeout":30}]}\n' "$(pin python)"
    ;;
  setup)
    {
      echo "RUSTUP_HOME=$RUNNER_TEMP/gie-rustup"
      echo "CARGO_HOME=$RUNNER_TEMP/gie-cargo"
    } >> "$GITHUB_ENV"
    export RUSTUP_HOME="$RUNNER_TEMP/gie-rustup" CARGO_HOME="$RUNNER_TEMP/gie-cargo"
    python3 e2e/harness/ci.py apt --group unit
    toolchain="$(pin toolchain)"
    rustup toolchain install "$toolchain" --profile minimal --component rustc,cargo,rust-std,rustfmt,clippy
    if [ "$2" = python ]; then
      bash e2e/harness/setup.sh --sglang-commit "$(pin sglang_commit)" --dynamo "$(pin dynamo)"
    fi
    ;;
  run)
    case "$2" in
      python)
        source .e2e-venv/env.sh
        E2E_TEMPLATE_SELFTEST=1 .e2e-venv/bin/python e2e/harness/ci.py python --packages PyYAML dockerfile-parse
        E2E_TEMPLATE_SELFTEST=1 .e2e-venv/bin/python e2e/harness/ci.py unit
        export PATH="$PWD/.e2e-venv/bin:$PATH"
        .e2e-venv/bin/python e2e/harness/ci.py python --packages maturin
        .e2e-venv/bin/python e2e/harness/ci.py bindings
        ;;
      cargo) python3 e2e/harness/ci.py cargo ;;
      *) echo "unknown job $2" >&2; exit 2 ;;
    esac
    ;;
  *) echo "usage: $0 plan|setup <id>|run <id>|report" >&2; exit 2 ;;
esac
