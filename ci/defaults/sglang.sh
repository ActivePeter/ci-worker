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
steps = {step.get("name"): step for step in job["steps"]}
if mode == "plan":
    print(json.dumps({"version": 1, "report": False, "jobs": [{
        "id": "cpu-unit",
        "python": steps["Set up Python"]["with"]["python-version"],
        "timeout": job["timeout-minutes"],
    }]}))
    sys.exit(0)

env = dict(os.environ)
for name in ("SGLANG_IS_IN_CI", "USE_VENV"):
    env[name] = str(stage["env"][name]).lower()

if mode == "setup":
    # The worker has no upstream rust-ext-build artifact.
    install = steps["Install dependencies"]
    env["UV_SYSTEM_PYTHON"] = str(install["env"]["UV_SYSTEM_PYTHON"])
    command = steps["Install protoc + Rust toolchain"]["run"] + "\n" + install["run"]
else:
    run_step = steps["Run test"]
    if "SGLANG_SKIP_RUST_TESTS" in run_step.get("env", {}):
        env["SGLANG_SKIP_RUST_TESTS"] = "false"
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
