#!/usr/bin/env bash
# Bridge the tested SHA's PR CPU stage to the public worker entry contract.
set -euo pipefail

case "${1:-}" in
  plan)
    python_version=$(
      yq -o=json '.jobs.run.steps' .github/workflows/_pr-test-stage-cpu.yml |
        jq -er '.[] | select((.uses // "") | startswith("actions/setup-python@")) | .with["python-version"] | strings'
    )
    yq -o=json '.jobs' .github/workflows/pr-test.yml |
      jq -ce --arg python "$python_version" '
        [ .[] | select(.uses == "./.github/workflows/_pr-test-stage-cpu.yml")
          | {id: .with.self_name, python: $python, timeout: 60} ]
        | if length == 0 then error("no PR CPU suites declared") else
            {version: 1, jobs: ., report: false}
          end'
    ;;
  setup)
    bash scripts/ci/utils/install_rust_protoc.sh
    UV_SYSTEM_PYTHON=1 uv pip install -e "python[dev]" --index-strategy unsafe-best-match --prerelease allow
    ;;
  run)
    export SGLANG_IS_IN_CI=true USE_VENV=false
    cd test
    exec python3 run_suite.py --hw cpu --suite "${2:?missing suite}"
    ;;
  report)
    # unit.yml reports the result of each suite job.
    ;;
  *)
    echo 'usage: sglang.sh {plan|setup <suite>|run <suite>|report}' >&2
    exit 2
    ;;
esac
