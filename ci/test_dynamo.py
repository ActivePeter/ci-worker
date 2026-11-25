"""Guard the bridge against silently dropping source workflow semantics."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ENTRY = Path(__file__).resolve().parent / "defaults/dynamo.sh"


class DynamoWorkflowTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.workflow = self.root / ".github/workflows/release-1.6.1-contracts.yml"
        self.workflow.parent.mkdir(parents=True)
        self.data = {"jobs": {
            "cpu-contracts": {"timeout-minutes": 20, "steps": [{"run": "true"}]},
            "rust-contracts": {"timeout-minutes": 90, "steps": [{"run": "true"}]},
        }}

    def entry(self, *args):
        self.workflow.write_text(json.dumps(self.data))
        return subprocess.run(
            ["bash", str(ENTRY), *args], cwd=self.root, text=True, capture_output=True,
            env=dict(os.environ, GIE_GIT_TOKEN="fixture-token", RUNNER_TEMP=str(self.root / "scratch"),
                     GITHUB_ENV=str(self.root / "job.env"), GITHUB_PATH=str(self.root / "job.path")),
        )

    def test_whole_target_jobs_are_planned_once_and_without_named_preparation(self):
        job = self.data["jobs"]["rust-contracts"]
        job["steps"] = [
            {"name": "renamed prerequisite", "run": "echo prepare >> observed"},
            {"name": "source cases", "run": "echo batch >> observed\necho nvext >> observed"},
        ]
        plan = self.entry("plan")
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertEqual([job["id"] for job in json.loads(plan.stdout)["jobs"]],
                         ["cpu-contracts", "rust-contracts"])
        result = self.entry("run", "rust-contracts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "observed").read_text(), "prepare\nbatch\nnvext\n")

    def test_missing_rust_contracts_fails_plan(self):
        del self.data["jobs"]["rust-contracts"]
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("缺少 rust-contracts", result.stderr)

    def test_workflow_with_only_unknown_action_fails_plan(self):
        self.data["jobs"]["cpu-contracts"]["steps"] = [{"uses": "./.github/actions/real-tests"}]
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow action for dynamo: ./.github/actions/real-tests", result.stderr)

    def test_sglang_action_is_rejected_for_dynamo(self):
        self.data["jobs"]["cpu-contracts"]["steps"].insert(
            0, {"uses": "./.github/actions/check-maintenance"},
        )
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow action for dynamo: ./.github/actions/check-maintenance",
                      result.stderr)

    def test_checkout_submodules_is_rejected(self):
        self.data["jobs"]["cpu-contracts"]["steps"].insert(
            0, {"uses": "actions/checkout@v4", "with": {"submodules": True}},
        )
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow action inputs for actions/checkout: submodules", result.stderr)

    def test_unsupported_job_expression_fails_plan(self):
        self.data["jobs"]["cpu-contracts"]["env"] = {"SHA": "${{ github.sha }}"}
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow expression: github.sha", result.stderr)

    def test_unsupported_condition_fails_plan(self):
        self.data["jobs"]["cpu-contracts"]["steps"] = [{"if": "steps.other.outputs.x", "run": "true"}]
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow if", result.stderr)

    def test_continue_on_error_fails_plan(self):
        self.data["jobs"]["cpu-contracts"]["steps"] = [{"continue-on-error": True, "run": "false"}]
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("continue-on-error", result.stderr)

    def test_non_bash_default_shell_fails_plan(self):
        self.data["defaults"] = {"run": {"shell": "pwsh"}}
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow shell: pwsh", result.stderr)

    def test_workflow_defaults_job_env_and_step_env_are_inherited(self):
        (self.root / "scope").mkdir()
        self.data["env"] = {"WORKSPACE": "${{ github.workspace }}", "VALUE": "workflow"}
        self.data["defaults"] = {"run": {"shell": "bash", "working-directory": "scope"}}
        job = self.data["jobs"]["cpu-contracts"]
        job["env"] = {"VALUE": "job", "TEMP": "${{ runner.temp }}"}
        job["steps"] = [
            {"run": 'echo "$PWD $WORKSPACE $TEMP $VALUE" > observed'},
            {"env": {"VALUE": "step"}, "run": 'echo "$VALUE" >> observed'},
        ]
        result = self.entry("run", "cpu-contracts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "scope/observed").read_text().splitlines(),
                         [f"{self.root}/scope {self.root} {self.root}/scratch job", "step"])

    def test_environment_path_and_explicit_secret_reach_only_their_consumers(self):
        tools = self.root / "bin"
        tools.mkdir()
        tool = tools / "source-command"
        tool.write_text("#!/bin/bash\necho source-command\n")
        tool.chmod(0o755)
        self.data["jobs"]["cpu-contracts"]["steps"] = [
            {"run": 'echo "$PWD/bin" >> "$GITHUB_PATH"; printf "MESSAGE<<END\nhello\nworld\nEND\n" >> "$GITHUB_ENV"'},
            {"env": {"GIE_GIT_TOKEN": "${{ secrets.GIE_GIT_TOKEN }}"},
             "run": 'test "$GIE_GIT_TOKEN" = fixture-token; source-command'},
            {"run": 'test -z "${GIE_GIT_TOKEN:-}"; printf "%s\n" "$MESSAGE" > observed'},
        ]
        result = self.entry("run", "cpu-contracts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source-command", result.stdout)
        self.assertEqual((self.root / "observed").read_text(), "hello\nworld\n")
        plan = self.entry("plan")
        self.assertTrue(json.loads(plan.stdout)["jobs"][0]["git_token"])

    def test_failed_step_propagates_and_only_always_still_runs(self):
        self.data["jobs"]["cpu-contracts"]["steps"] = [
            {"run": "exit 9"},
            {"run": "echo skipped >> observed"},
            {"if": "always()", "run": "echo always >> observed"},
        ]
        result = self.entry("run", "cpu-contracts")
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual((self.root / "observed").read_text(), "always\n")
