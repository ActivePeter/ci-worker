"""Run the supported shell steps of a workflow owned by the tested checkout."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


DYNAMO_ACTIONS = {
    "actions/checkout": {"persist-credentials"},
    "actions/setup-python": {"python-version"},
    "taiki-e/install-action": {"tool"},
    "goodputai/goodput-infer-ext/.github/actions/gie-git-auth": {"token", "lockfile"},
    "actions/cache/restore": {"path", "key", "restore-keys"},
    "actions/cache/save": {"path", "key"},
    "actions/upload-artifact": {"name", "include-hidden-files", "path"},
}
SGLANG_ACTIONS = {
    "actions/checkout": {"ref"},
    "actions/setup-python": {"python-version"},
    "astral-sh/setup-uv": set(),
    "actions/cache": {"path", "key", "restore-keys"},
    "actions/cache/restore": {"path", "key", "restore-keys"},
    "actions/cache/save": {"path", "key"},
    "actions/download-artifact": {"name", "path"},
    "Swatinem/rust-cache": {"workspaces", "shared-key", "save-if"},
    "./.github/actions/check-pr-test-health": set(),
    "./.github/actions/check-maintenance": set(),
    "./.github/actions/download-rust-ext": {"artifact_name"},
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
SGLANG_CONTINUE_FLAG = (
    "fromJson(inputs.check_changes).continue_on_error == 'true' && '--continue-on-error' || ''"
)
SGLANG_EXPRESSIONS = {
    "(fromJson(inputs.caller_inputs).skip_pr_test_health_check || fromJson(inputs.caller_inputs).test_parallel_dispatch || fromJson(inputs.caller_inputs).run_all_tests) && 'true' || 'false'": "false",
    "github.ref == 'refs/heads/main' && 'true' || 'false'": "false",
    "steps.rust_ext.outcome == 'success' && 'none' || ''": "",
    "fromJson(inputs.check_changes).rust_workspace == 'true' && 'false' || 'true'": "true",
    "fromJson(inputs.check_changes).partition_model_sha": "",
    "steps.hf_cache_before.outputs.bytes": "0",
    "inputs.self_name": "base-a-test-cpu",
}



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
        self.actions = SGLANG_ACTIONS if engine == "sglang" else DYNAMO_ACTIONS
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

    def expand(self, value, *, allow_secret=False, local=None):
        if isinstance(value, bool):
            return str(value).lower()

        expressions = self.expressions | (local or {})

        def substitute(match):
            expression = match[1].strip()
            if expression == TOKEN_REF and not allow_secret:
                raise ValueError("workflow secrets are supported only in env")
            if expression not in expressions:
                raise ValueError(f"unsupported workflow expression: {expression}")
            return expressions[expression]

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
        self.expressions.setdefault("fromJson(inputs.run_timeout_minutes)", str(job_timeout))
        steps = []
        settings = {"id": name, "timeout": job_timeout}
        scopes = [self.data, job]
        test_steps = 0
        for step in job["steps"]:
            active = self.active(step.get("if", ""))
            unknown = set(step) - SUPPORTED_EXECUTION_KEYS
            # The upstream artifact download is not selected without an artifact.
            if (self.engine == "sglang" and not active
                    and step.get("uses", "").startswith("actions/download-artifact@")):
                unknown.discard("continue-on-error")
            if unknown:
                raise ValueError(f"unsupported workflow step keys: {', '.join(sorted(unknown))}")
            scopes.append(step)
            values = self.environment_for(step)
            shell = self.expand(step.get("shell", job_defaults.get("shell", "")))
            if shell not in {"", "bash"}:
                raise ValueError(f"unsupported workflow shell: {shell}")
            if ("uses" in step) == ("run" in step):
                raise ValueError("workflow step requires exactly one of uses or run")
            if "uses" in step:
                action = step["uses"].split("@", 1)[0]
                if action not in self.actions:
                    raise ValueError(f"unsupported workflow action for {self.engine}: {action}")
                unsupported = set(step.get("with") or {}) - self.actions[action]
                if unsupported:
                    raise ValueError(f"unsupported workflow action inputs for {action}: {', '.join(sorted(unsupported))}")
                if active and action == "actions/setup-python":
                    settings["python"] = self.expand(step["with"]["python-version"])
                if active and action == "taiki-e/install-action":
                    settings["nextest"] = self.expand(step["with"]["tool"])
                continue
            command = step["run"]
            is_sglang_suite = self.engine == "sglang" and "run_suite.py" in command
            if is_sglang_suite:
                test_steps += 1
            command = self.expand(command)
            if is_sglang_suite:
                command = 'set -o pipefail\n{\n' + command.rstrip() + '\n} 2>&1 | tee "$CI_OUT/run-suite.log"'
            working = self.expand(step.get("working-directory", job_defaults.get("working-directory", ".")))
            step_timeout = int(self.expand(step.get("timeout-minutes", job_timeout)))
            if is_sglang_suite:
                settings["run_timeout"] = step_timeout
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


def sglang_pr_continue_on_error(workflow):
    source = Path(".github/workflows/_pr-test-check-changes.yml")
    steps = yaml.safe_load(source.read_text())["jobs"]["run"]["steps"]
    commands = {step["id"]: step["run"] for step in steps if "id" in step and "run" in step}
    context = {
        "github.event_name": "pull_request",
        "github.event_name == 'schedule'": "false",
        "inputs.run_all_tests": "false",
        "inputs.force_continue_on_error": "false",
    }
    with tempfile.TemporaryDirectory(prefix="ci22-sglang-check-") as directory:
        output = Path(directory) / "output"

        def run(step, field):
            output.write_text("")
            subprocess.run(
                ["bash", "-e", "-c", workflow.expand(commands[step], local=context)],
                env=dict(workflow.environment, GITHUB_OUTPUT=str(output)),
                check=True, stdout=subprocess.DEVNULL,
            )
            value = dict(environment_updates(output.read_text().splitlines())).get(field)
            if value not in {"true", "false"}:
                raise ValueError(f"SGLang check-changes did not emit boolean {field}")
            return value

        context["steps.run-mode.outputs.run_all_tests"] = run("run-mode", "run_all_tests")
        value = run("set-continue-on-error", "continue_on_error")
    return "--continue-on-error" if value == "true" else ""


def sglang_partitions(stage):
    caller = Path(".github/workflows/pr-test.yml")
    upstream = yaml.safe_load(caller.read_text())["jobs"]["base-a-test-cpu"]
    if upstream.get("uses") != f"./{stage}":
        raise ValueError("SGLang CPU suite does not call the expected source stage")
    parameters = upstream["with"]
    suite = parameters["self_name"]
    minutes = int(parameters["run_timeout_minutes"])
    if minutes < 1:
        raise ValueError("SGLang CPU suite timeout must be positive")
    result = subprocess.run(
        [sys.executable, "-I", "scripts/ci/utils/compute_partitions.py",
         "--output-format", "json", "--pr-test-yml", str(caller), "--full-parallel", "true"],
        check=True, stdout=subprocess.PIPE, text=True,
    )
    layout = json.loads(result.stdout)[suite]
    size, indices = layout["size"], layout["arr"]
    if not isinstance(size, int) or size < 1 or sorted(indices) != list(range(size)):
        raise ValueError("SGLang partition plan has invalid indices")
    return suite, size, indices, minutes


def main():
    engine, mode, *args = sys.argv[1:]
    if mode == "report":
        return
    if engine == "dynamo":
        path = Path(".github/workflows/release-1.6.1-contracts.yml")
        selected = {"cpu-contracts": "cpu-contracts", "rust-contracts": "rust-contracts"}
    else:
        path = Path(".github/workflows/_pr-test-stage-cpu.yml")
        selected = {}
    if not path.is_file():
        raise ValueError(f"该提交无桥接对象：缺少 {path}")
    workflow = Workflow(path, engine)
    jobs = workflow.data.get("jobs", {})
    missing = set(selected.values()) - jobs.keys()
    if missing:
        raise ValueError(f"该提交无桥接对象：{path} 缺少 {', '.join(sorted(missing))}")
    if engine == "sglang":
        if "run" not in jobs:
            raise ValueError("SGLang CPU stage has no run job")
        workflow.expressions[SGLANG_CONTINUE_FLAG] = sglang_pr_continue_on_error(workflow)
        suite, size, indices, minutes = sglang_partitions(path)
        selected = {f"cpu-unit-{partition}": "run" for partition in indices}
        entries = {}
        for name, partition in zip(selected, indices):
            if mode != "plan" and args != [name]:
                continue
            workflow.expressions.update({
                "inputs.self_name": suite,
                "matrix.partition": str(partition),
                "fromJson(inputs.partitions)[inputs.self_name].size": str(size),
                "fromJson(inputs.run_timeout_minutes)": str(minutes),
            })
            entries[name] = workflow.describe(name, jobs["run"])
    else:
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
    except (KeyError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
