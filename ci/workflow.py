"""Run the supported shell steps of a workflow owned by the tested checkout."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml


ACTIONS = {
    "actions/checkout": "unit checkout at the tested SHA",
    "actions/setup-python": "unit setup-python using the source step's version",
    "taiki-e/install-action": "unit nextest installer using the source step's tool",
    "goodputai/goodput-infer-ext/.github/actions/gie-git-auth": "ci/git-auth.sh",
    "astral-sh/setup-uv": "unit setup-uv",
    "actions/cache": "optional source cache, omitted",
    "actions/cache/restore": "optional source cache, omitted",
    "actions/cache/save": "optional source cache, omitted",
    "actions/upload-artifact": "unit job receipt, source-specific artifact omitted",
    "actions/download-artifact": "SGLang source-build fallback",
    "Swatinem/rust-cache": "SGLang source-build fallback without source cache",
    "./.github/actions/check-pr-test-health": "source PR orchestration, omitted",
    "./.github/actions/check-maintenance": "source PR orchestration, omitted",
    "./.github/actions/download-rust-ext": "SGLang source-build fallback",
}
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
TOKEN_REF = "secrets.GIE_GIT_TOKEN"
SUPPORTED_EXECUTION_KEYS = {
    "name", "id", "if", "uses", "with", "run", "env", "shell",
    "working-directory", "timeout-minutes",
}
BASE_CONDITIONS = {
    "always()": True,
    "runner.environment == 'self-hosted'": False,
    "always() && !cancelled() && steps.contract-build-cache.outputs.cache-hit != 'true'": False,
}
SGLANG_CONDITIONS = {
    "fromJson(inputs.check_changes).main_package == 'true'": True,
    "fromJson(inputs.check_changes).main_package == 'true' || fromJson(inputs.check_changes).renderer == 'true'": True,
    "steps.rust_ext.outputs.hit != 'true'": True,
    "steps.rust_ext.outcome != 'success'": True,
    "inputs.rust_ext_artifact != ''": False,
    "fromJson(inputs.check_changes).partition_model_sha != ''": False,
    "steps.hf_cache_save.outputs.save == 'true'": False,
}
SGLANG_EXPRESSIONS = {
    "(fromJson(inputs.caller_inputs).skip_pr_test_health_check || fromJson(inputs.caller_inputs).test_parallel_dispatch || fromJson(inputs.caller_inputs).run_all_tests) && 'true' || 'false'": "false",
    "github.ref == 'refs/heads/main' && 'true' || 'false'": "false",
    "steps.rust_ext.outcome == 'success' && 'none' || ''": "",
    "fromJson(inputs.check_changes).rust_workspace == 'true' && 'false' || 'true'": "true",
    "fromJson(inputs.check_changes).continue_on_error == 'true' && '--continue-on-error' || ''": "--continue-on-error",
    "fromJson(inputs.check_changes).partition_model_sha": "",
    "steps.hf_cache_before.outputs.bytes": "0",
    "inputs.self_name": "base-a-test-cpu",
}
SGLANG_PARTITION_OPTIONS = (
    " --auto-partition-id ${{ matrix.partition }}",
    " --auto-partition-size ${{ fromJson(inputs.partitions)[inputs.self_name].size }}",
    " --partition-model-file /tmp/partition-model.json",
)


def defaults(mapping):
    entry = mapping.get("defaults", {})
    if set(entry) - {"run"} or set(entry.get("run", {})) - {"shell", "working-directory"}:
        raise ValueError("unsupported workflow defaults")
    return entry.get("run", {})


def read_updates(path, start):
    if not path or not Path(path).is_file():
        return []
    with open(path, "rb") as stream:
        stream.seek(start)
        return stream.read().decode().splitlines()


def environment_updates(lines):
    records = iter(lines)
    for line in records:
        name, separator, value = line.partition("=")
        variable, delimiter, stop = name.partition("<<")
        if delimiter:
            stop = line.split("<<", 1)[1]
            value_lines = []
            for record in records:
                if record == stop:
                    break
                value_lines.append(record)
            else:
                raise ValueError("unterminated GITHUB_ENV record")
            yield variable, "\n".join(value_lines)
        elif separator:
            yield name, value
        else:
            raise ValueError("invalid GITHUB_ENV record")


def condition_name(condition):
    if isinstance(condition, bool):
        return condition
    condition = condition.strip()
    match = EXPRESSION.fullmatch(condition)
    return match[1].strip() if match else condition


def position(path):
    return Path(path).stat().st_size if path and Path(path).is_file() else 0


class Workflow:
    def __init__(self, path, engine):
        self.engine = engine
        self.data = yaml.safe_load(path.read_text())
        self.environment = dict(os.environ, GITHUB_WORKSPACE=str(Path.cwd()))
        token = self.environment.pop("GIE_GIT_TOKEN", "")
        self.expressions = {
            "github.workspace": self.environment["GITHUB_WORKSPACE"],
            "runner.temp": self.environment.get("RUNNER_TEMP", ""),
            TOKEN_REF: token,
        }
        self.conditions = BASE_CONDITIONS.copy()
        if engine == "sglang":
            self.expressions.update(SGLANG_EXPRESSIONS)
            self.conditions.update(SGLANG_CONDITIONS)
        self.defaults = defaults(self.data)

    def expand(self, value, *, allow_secret=False):
        if isinstance(value, bool):
            return str(value).lower()

        def substitute(match):
            expression = match[1].strip()
            if expression == TOKEN_REF and not allow_secret:
                raise ValueError("workflow secrets are supported only in env")
            if expression not in self.expressions:
                raise ValueError(f"unsupported workflow expression: {expression}")
            return self.expressions[expression]

        value = EXPRESSION.sub(substitute, str(value))
        if "${{" in value:
            raise ValueError("malformed workflow expression")
        return value

    def environment_for(self, *scopes):
        merged = {}
        for scope in scopes:
            merged.update({key: self.expand(value, allow_secret=True)
                           for key, value in scope.get("env", {}).items()})
        return merged

    def active(self, condition):
        condition = condition_name(condition)
        if isinstance(condition, bool):
            return condition
        if not condition:
            return True
        if condition not in self.conditions:
            raise ValueError(f"unsupported workflow if: {condition}")
        return self.conditions[condition]

    def describe(self, name, job):
        if set(job) - {"name", "if", "runs-on", "timeout-minutes", "env",
                       "defaults", "strategy", "steps", "permissions"}:
            raise ValueError(f"unsupported workflow job keys in {name}")
        if "strategy" in job and (self.engine != "sglang" or
                                  set(job["strategy"].get("matrix", {})) != {"partition"}):
            raise ValueError(f"unsupported workflow matrix in {name}")
        if not self.active(job.get("if", "")):
            raise ValueError(f"required workflow job is disabled: {name}")
        job_defaults = self.defaults | defaults(job)
        self.environment_for(self.data, job)
        job_timeout = int(self.expand(job.get("timeout-minutes", 60)))
        self.expressions["fromJson(inputs.run_timeout_minutes)"] = str(job_timeout)
        steps = []
        settings = {"id": name, "timeout": job_timeout}
        scopes = [self.data, job]
        test_steps = 0
        for step in job["steps"]:
            unknown = set(step) - SUPPORTED_EXECUTION_KEYS
            if unknown:
                raise ValueError(f"unsupported workflow step keys: {', '.join(sorted(unknown))}")
            active = self.active(step.get("if", ""))
            scopes.append(step)
            values = self.environment_for(step)
            shell = self.expand(step.get("shell", job_defaults.get("shell", "")))
            if shell not in {"", "bash"}:
                raise ValueError(f"unsupported workflow shell: {shell}")
            if ("uses" in step) == ("run" in step):
                raise ValueError("workflow step requires exactly one of uses or run")
            if "uses" in step:
                action = step["uses"].split("@", 1)[0]
                if action not in ACTIONS:
                    raise ValueError(f"unsupported workflow action: {action}")
                if active and action == "actions/setup-python":
                    settings["python"] = self.expand(step["with"]["python-version"])
                if active and action == "taiki-e/install-action":
                    settings["nextest"] = self.expand(step["with"]["tool"])
                continue
            command = step["run"]
            is_sglang_suite = self.engine == "sglang" and "run_suite.py" in command
            if is_sglang_suite:
                test_steps += 1
                for option in SGLANG_PARTITION_OPTIONS:
                    command = command.replace(option, "")
            command = self.expand(command)
            if is_sglang_suite:
                command = 'set -o pipefail\n{\n' + command.rstrip() + '\n} 2>&1 | tee "$CI_OUT/run-suite.log"'
            working = self.expand(step.get("working-directory", job_defaults.get("working-directory", ".")))
            step_timeout = int(self.expand(step.get("timeout-minutes", job_timeout)))
            if active:
                steps.append((step, command, values, shell, working, step_timeout))
        if not steps or (self.engine == "sglang" and test_steps != 1):
            raise ValueError(f"required workflow job has no supported test entry: {name}")
        settings["git_token"] = any(
            TOKEN_REF in str(value)
            for scope in scopes for value in scope.get("env", {}).values()
        )
        return settings, steps

    def run(self, job, steps):
        env = self.environment | self.environment_for(self.data, job)
        path_file = env.get("GITHUB_PATH")
        env_file = env.get("GITHUB_ENV")
        failed = 0
        for step, command, values, shell, working, timeout in steps:
            if failed and condition_name(step.get("if", "")) != "always()":
                continue
            path_offset = position(path_file)
            env_offset = position(env_file)
            print(f"{step.get('name', 'run')}", flush=True)
            flags = ["--noprofile", "--norc", "-eo", "pipefail"] if shell else ["-e"]
            try:
                result = subprocess.run(
                    ["bash", *flags, "-c", command], cwd=working,
                    env=env | values, timeout=timeout * 60,
                )
                failed = failed or result.returncode
            except subprocess.TimeoutExpired:
                print("workflow step timed out", file=sys.stderr)
                failed = failed or 124
            env.update(environment_updates(read_updates(env_file, env_offset)))
            for directory in read_updates(path_file, path_offset):
                if directory:
                    env["PATH"] = directory + os.pathsep + env["PATH"]
        sys.exit(failed)


def main():
    engine, mode, *args = sys.argv[1:]
    if mode == "report":
        return
    if engine == "dynamo":
        path = Path(".github/workflows/release-1.6.1-contracts.yml")
        selected = {"cpu-contracts": "cpu-contracts", "rust-contracts": "rust-contracts"}
    else:
        path = Path(".github/workflows/_pr-test-stage-cpu.yml")
        selected = {"cpu-unit": "run"}
    if not path.is_file():
        raise ValueError(f"该提交无桥接对象：缺少 {path}")
    workflow = Workflow(path, engine)
    jobs = workflow.data.get("jobs", {})
    missing = set(selected.values()) - jobs.keys()
    if missing:
        raise ValueError(f"该提交无桥接对象：{path} 缺少 {', '.join(sorted(missing))}")
    entries = {name: workflow.describe(name, jobs[key]) for name, key in selected.items()}
    if mode == "plan" and not args:
        print(json.dumps({"version": 1, "report": False, "jobs": [row[0] for row in entries.values()]}))
        return
    if mode not in {"setup", "run"} or len(args) != 1 or args[0] not in entries:
        raise ValueError("invalid workflow bridge invocation")
    if mode == "run":
        settings, steps = entries[args[0]]
        if settings["git_token"] and not workflow.expressions[TOKEN_REF]:
            raise ValueError("GIE_GIT_TOKEN is required by the source workflow")
        workflow.run(jobs[selected[args[0]]], steps)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError) as error:
        sys.exit(str(error))
