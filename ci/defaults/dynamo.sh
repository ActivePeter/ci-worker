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

jobs = yaml.safe_load(Path(workflow).read_text()).get("jobs", {})
if not {"cpu-contracts", "rust-contracts"} <= jobs.keys():
    sys.exit(f"该提交无桥接对象：{workflow} 缺少 cpu-contracts 或 rust-contracts")
cpu, rust = jobs["cpu-contracts"], jobs["rust-contracts"]
rust_labels = ("llm-unit", "llm-http-batch", "llm-http-nvext")
gate_label = re.compile(r"--label (\S+)")


def gate_lines(command):
    return command.replace("\\\n", " ").splitlines()


def is_gate(line):
    return ".github/ci/run_rust_gate.py" in line and gate_label.search(line) is not None


registered = {
    gate_label.search(line)[1]
    for step in rust["steps"]
    for line in gate_lines(step.get("run", ""))
    if is_gate(line)
}


def action_value(job, action, key):
    return next(
        (step["with"][key] for step in job["steps"]
         if step.get("uses", "").startswith(action + "@") and key in step.get("with", {})),
        "",
    )


if mode == "plan" and not args:
    python = action_value(cpu, "actions/setup-python", "python-version")
    nextest = action_value(rust, "taiki-e/install-action", "tool")
    matrix = [{"id": "cpu-contracts", "timeout": cpu["timeout-minutes"], "python": python}]
    matrix.extend({"id": label, "timeout": rust["timeout-minutes"], "nextest": nextest}
                  for label in rust_labels if label in registered)
    print(json.dumps({"version": 1, "report": False, "jobs": matrix}))
    sys.exit(0)
if mode not in {"setup", "run"} or len(args) != 1:
    sys.exit(f"invalid Dynamo entry invocation: {sys.argv[2:]}")

ident = args[0]
if ident != "cpu-contracts" and ident not in registered.intersection(rust_labels):
    sys.exit(f"unknown Dynamo contract {ident}")
if mode == "setup":
    sys.exit(0)

job = cpu if ident == "cpu-contracts" else rust
env = dict(os.environ, GITHUB_WORKSPACE=str(Path.cwd()))
secret = env.pop("GIE_GIT_TOKEN", "")
env.update({key: str(value) for key, value in job.get("env", {}).items()})


def apply_environment_file(path, offset):
    if not path or not Path(path).exists():
        return
    with open(path) as stream:
        stream.seek(offset)
        for record in stream:
            key, separator, value = record.rstrip("\n").partition("=")
            if not separator:
                sys.exit(f"unsupported workflow environment record in {path}")
            env[key] = value


failed = 0
for step in job["steps"]:
    if "run" not in step:
        continue
    condition = step.get("if", "").strip()
    if condition == "runner.environment == 'self-hosted'":
        continue
    if condition not in {"", "always()"}:
        sys.exit(f"unsupported Dynamo workflow step condition: {condition}")
    if failed and condition != "always()":
        continue
    command = step["run"]
    if ident != "cpu-contracts":
        lines = gate_lines(command)
        if any(is_gate(line) for line in lines):
            command = "\n".join(
                line for line in lines if not is_gate(line) or gate_label.search(line)[1] == ident
            )
    step_env = env.copy()
    for key, value in step.get("env", {}).items():
        if value == "${{ secrets.GIE_GIT_TOKEN }}":
            if key != "GIE_GIT_TOKEN" or not secret:
                sys.exit(f"{key} is required by {step.get('name', 'the Dynamo step')}")
            step_env[key] = secret
            continue
        value = str(value).replace("${{ runner.temp }}", env.get("RUNNER_TEMP", ""))
        if "${{" in value:
            sys.exit(f"unsupported GitHub expression for {key}")
        step_env[key] = value
    if "${{" in command:
        sys.exit(f"unsupported GitHub expression in {step.get('name', 'the Dynamo step')}")
    env_file = env.get("GITHUB_ENV")
    before = Path(env_file).stat().st_size if env_file and Path(env_file).exists() else 0
    print(f"{workflow}: {step.get('name', 'run')} ({ident})", flush=True)
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", command],
        env=step_env, cwd=step.get("working-directory"),
    )
    apply_environment_file(env_file, before)
    failed = failed or result.returncode
sys.exit(failed)

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
