#!/usr/bin/env bash
# Bridge the checkout's input-admission and LLM contracts when declared.
set -euo pipefail

workflow=.github/workflows/release-1.6.1-contracts.yml
if [[ ! -f "$workflow" ]]; then
  workflow=.github/workflows/contracts.yml
fi
if [[ -f "$workflow" ]]; then
  exec /usr/bin/python3 -I - "$workflow" "$@" <<'PYTHON'
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

workflow, mode, *args = sys.argv[1:]
if mode == "report":
    sys.exit(0)

upstream = yaml.safe_load(Path(workflow).read_text())["jobs"]
cpu, rust = upstream["cpu-contracts"], upstream["rust-contracts"]
cpu_steps = {step.get("name"): step for step in cpu["steps"]}
rust_steps = {step.get("name"): step for step in rust["steps"]}
cpu_install = (
    "Install CPU test dependencies",
    "Install input admission CPU dependencies",
)
cpu_test = "Test input admission against the installed extension"
rust_setup = (
    "Prepare pinned Harmony vocabularies before parallel tests",
    "Install JUnit policy dependencies",
    "Install native build prerequisites and local NATS",
    "Install components for the repository Rust toolchain",
    "Prepare verified Harmony vocabulary",
)
rust_labels = ("llm-unit", "llm-http-batch", "llm-http-nvext")
rust_commands = {}
for step in rust["steps"]:
    lines = step.get("run", "").replace("\\\n", " ").splitlines()
    gates = [line for line in lines if ".github/ci/run_rust_gate.py" in line]
    if not gates:
        continue
    preamble = lines[:lines.index(gates[0])]
    for gate in gates:
        match = re.search(r"--label (\S+)", gate)
        if match and match[1] in rust_labels:
            rust_commands[match[1]] = (step, "\n".join([*preamble, gate]))

for label in rust_labels[:2]:
    if label not in rust_commands:
        sys.exit(f"{workflow} does not register the required Rust contract {label}")

if mode == "plan" and not args:
    python = next(step["with"]["python-version"] for step in cpu["steps"]
                  if step.get("uses", "").startswith("actions/setup-python@"))
    nextest = rust_steps["Install pinned nextest and gate dependencies"]["with"]["tool"]
    jobs = [{"id": "cpu-contracts", "timeout": cpu["timeout-minutes"], "python": python}]
    jobs.extend({"id": label, "timeout": rust["timeout-minutes"], "nextest": nextest}
                for label in rust_labels if label in rust_commands)
    print(json.dumps({"version": 1, "report": False, "jobs": jobs}))
    sys.exit(0)
if mode not in {"setup", "run"} or len(args) != 1:
    sys.exit(f"invalid Dynamo entry invocation: {sys.argv[2:]}")

env = dict(os.environ, GITHUB_WORKSPACE=str(Path.cwd()))


def run_step(step, command=None):
    step_env = env.copy()
    for key, value in step.get("env", {}).items():
        if value == "${{ secrets.GIE_GIT_TOKEN }}":
            if not step_env.get(key):
                sys.exit(f"{key} is required by {step['name']}")
            continue
        value = str(value).replace("${{ runner.temp }}", env.get("RUNNER_TEMP", ""))
        if "${{" in value:
            sys.exit(f"unsupported GitHub expression for {key} in {step['name']}")
        step_env[key] = value
    command = step["run"] if command is None else command
    if "${{" in command:
        sys.exit(f"unsupported GitHub expression in {step['name']}")
    print(f"{workflow}: {step['name']} ({args[0]})", flush=True)
    result = subprocess.run(["bash", "-eo", "pipefail", "-c", command], env=step_env)
    if result.returncode:
        sys.exit(result.returncode)


job = args[0]
if job == "cpu-contracts":
    for name in cpu_install if mode == "setup" else (cpu_test,):
        run_step(cpu_steps[name])
elif job in rust_commands:
    env.update({key: str(value) for key, value in rust.get("env", {}).items()})
    if mode == "setup":
        for name in rust_setup:
            run_step(rust_steps[name])
    else:
        run_step(*rust_commands[job])
else:
    sys.exit(f"unknown Dynamo contract {job}")
PYTHON
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
