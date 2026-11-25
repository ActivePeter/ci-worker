#!/usr/bin/env bash
# Bridge the tested checkout's CPU stage onto the public worker entry contract.
set -euo pipefail
exec /usr/bin/python3 -I - "$@" <<'PY'
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

mode, *args = sys.argv[1:]
if mode == "report":
    sys.exit(0)
if mode not in {"plan", "setup", "run"} or (mode != "plan" and args != ["cpu-unit"]):
    sys.exit(f"invalid SGLang entry invocation: {sys.argv[1:]}")

stage = yaml.safe_load(Path(".github/workflows/_pr-test-stage-cpu.yml").read_text())
job = stage["jobs"]["run"]
steps = job["steps"]
if mode == "plan":
    print(json.dumps({"version": 1, "report": False, "jobs": [{
        "id": "cpu-unit",
        "python": next(
            step["with"]["python-version"] for step in steps
            if step.get("uses", "").startswith("actions/setup-python@")
        ),
        "timeout": job["timeout-minutes"],
    }]}))
    sys.exit(0)

env = dict(os.environ)
for name in ("SGLANG_IS_IN_CI", "USE_VENV"):
    env[name] = str(stage["env"][name]).lower()

if mode == "setup":
    # The worker has no upstream rust-ext-build artifact.
    install_steps = [
        step for step in steps
        if any(marker in step.get("run", "") for marker in ("install_rust_protoc.sh", "uv pip install"))
    ]
    for step in install_steps:
        step_env = dict(env, **{key: str(value) for key, value in step.get("env", {}).items()
                               if "${{" not in str(value)})
        result = subprocess.call(["bash", "-eo", "pipefail", "-c", step["run"]], env=step_env)
        if result:
            sys.exit(result)
    sys.exit(0)
else:
    run_step = next(step for step in steps if "run_suite.py" in step.get("run", ""))
    if "SGLANG_SKIP_RUST_TESTS" in run_step.get("env", {}):
        # The upstream rust_workspace expression defaults to skipping Rust tests.
        env["SGLANG_SKIP_RUST_TESTS"] = "true"
    # An unpartitioned run keeps the entire registered suite on this runner.
    command = re.sub(
        r" --(?:auto-partition-id|auto-partition-size|partition-model-file) (?:\$\{\{[^\n]*?\}\}|\S+)",
        "",
        run_step["run"],
    ).replace("${{ inputs.self_name }}", "base-a-test-cpu").replace(
        "$CONTINUE_ON_ERROR_FLAG", "--continue-on-error",
    )
    if "${{" in command:
        sys.exit("unsupported GitHub expression in the SGLang CPU test command")
    print(command.rstrip(), flush=True)
    command = '{\n' + command + '\n} 2>&1 | tee "$CI_OUT/run-suite.log"'

sys.exit(subprocess.call(["bash", "-eo", "pipefail", "-c", command], env=env))
PY
