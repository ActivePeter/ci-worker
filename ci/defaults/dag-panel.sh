#!/usr/bin/env bash
# Public-worker entry. Keep the six existing GitHub checks and the UI1 browser proof.
set -euo pipefail
phase="${1:-}"
case "$phase" in
  plan)
    /usr/bin/python3 -I - <<'PLAN'
import json, re
from pathlib import Path
go = re.search(r'^toolchain\s+go(\S+)\s*$', Path('go.mod').read_text(), re.M)
if not go:
    raise ValueError('dag-panel go.mod must declare a toolchain')
node = Path('collab/.nvmrc').read_text().strip().removeprefix('v')
pnpm = json.loads(Path('web/package.json').read_text())['packageManager'].split('@', 1)[1]
jobs = [dict(id=name, timeout=30, python='3.12', go=True, go_version=go.group(1), node=node, pnpm=pnpm,
             fetch_depth=0 if name == 'lint' else 1)
        for name in ['lint', 'unit', 'smoke', 'regression', 'performance', 'collector']]
# Old PR heads predate UI1. The frozen legacy default still runs all six checks.
if Path('testflows/machine-range-preview.cjs').is_file():
    jobs.append(dict(id='machine-ui1', timeout=30, python='3.12', go=True, go_version=go.group(1), node=node, pnpm=pnpm))
print(json.dumps(dict(version=1, jobs=jobs, report=False)))
PLAN
    ;;
  setup)
    # build_deploy.py is exercised by collector runtime-identity fixtures.
    # setup-python's isolated interpreter does not inherit Ubuntu's python3-yaml.
    if [[ "${2:?job required}" == collector ]]; then
      python3 -m pip install --disable-pip-version-check PyYAML==6.0.3
    fi
    case "${2:?job required}" in
      lint|unit|collector|machine-ui1)
        pnpm --dir web install --frozen-lockfile
        pnpm --dir web build
        ;;
    esac
    if [[ "$2" == lint ]]; then
      go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.11.4
      go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.8
      echo "$(go env GOPATH)/bin" >> "$GITHUB_PATH"
    elif [[ "$2" == machine-ui1 ]]; then
      version=$(/usr/bin/python3 -I -c "import json; print(json.load(open('collab/package-lock.json'))['packages']['node_modules/playwright']['version'])")
      tools="${RUNNER_TEMP:?}/dag-panel-browser"
      npm install --global --prefix "$tools" --no-audit --no-fund "playwright@$version"
      export PATH="$tools/bin:$PATH"
      echo "$tools/bin" >> "$GITHUB_PATH"
      echo "DAG_PLAYWRIGHT_MODULE=$tools/lib/node_modules/playwright" >> "$GITHUB_ENV"
      playwright install --with-deps chromium
      mkdir -p dist/dag-panel-artifact/bundle
      go build -o dist/dag-panel-artifact/bundle/dag-panel ./cmd/task-tree-trial
    fi
    ;;
  run)
    case "${2:?job required}" in
      lint)
        lint_base=$(git merge-base HEAD origin/main)
        if [[ "$lint_base" == "$(git rev-parse HEAD)" ]]; then lint_base=$(git rev-parse HEAD^); fi
        golangci-lint run --new-from-rev "$lint_base" ./... || { rc=$?; [[ "$rc" == 5 ]] || exit "$rc"; }
        actionlint -color
        ;;
      unit)
        go mod download
        go mod verify
        go build ./...
        go test -race ./...
        go test ./... -coverprofile="$CI_OUT/coverage.out" -covermode=atomic
        ;;
      smoke) go test -v -tags=smoke,no_web ./tests/e2e/... ;;
      regression) go test -v -tags=regression,no_web ./tests/e2e/... ;;
      performance) go test -bench=. -benchmem -tags=performance,no_web ./tests/performance/... ;;
      collector)
        python3 -m unittest discover -s tools/machine-collector -v
        tests=(testflows/machine-occupancy.cjs)
        if [[ -f testflows/timeline-range.cjs ]]; then tests+=(testflows/timeline-range.cjs); fi
        node --test "${tests[@]}"
        for script in core/task_machines.js core/task_machines_view.js core/task_timeline_range.js; do
          if [[ -f "$script" ]]; then node --check "$script"; fi
        done
        bash -n tools/machine-collector/install.sh
        go test ./cmd/task-tree-trial/... ./core/ ./internal/machineconfig/...
        go build -o "$RUNNER_TEMP/machine-panel" ./cmd/task-tree-trial
        go test -c -o "$RUNNER_TEMP/machine-panel-tests" ./cmd/task-tree-trial
        ;;
      machine-ui1)
        bash ci/check-toolchain.sh
        node testflows/machine-preview.cjs
        cp -a testflows/evidence/machine-occupancy/. "$CI_OUT/"
        ;;
      *) echo "unknown job: $2" >&2; exit 2 ;;
    esac
    ;;
  *) echo 'usage: public-unit.sh plan|setup JOB|run JOB' >&2; exit 2 ;;
esac
