"""Exercise the source SGLang stage through the shared workflow parser."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import plan

ENTRY = Path(__file__).resolve().parent / "defaults/sglang.sh"


class SglangEntryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.src = Path(scratch.name)
        self.workflow = self.src / ".github/workflows/_pr-test-stage-cpu.yml"
        self.workflow.parent.mkdir(parents=True)
        (self.src / "test").mkdir()
        (self.workflow.parent / "pr-test.yml").write_text(json.dumps({"jobs": {
            "base-a-test-cpu": {"uses": "./.github/workflows/_pr-test-stage-cpu.yml",
                                "with": {"self_name": "base-a-test-cpu", "run_timeout_minutes": "12"}},
        }}))
        self.check_changes = self.workflow.parent / "_pr-test-check-changes.yml"
        self.check_changes.write_text(json.dumps({"jobs": {"run": {"steps": [
            {"id": "run-mode", "run": 'test "${{ github.event_name }}" = pull_request; echo "run_all_tests=false" >> "$GITHUB_OUTPUT"'},
            {"id": "set-continue-on-error", "run": 'echo "continue_on_error=${{ steps.run-mode.outputs.run_all_tests }}" >> "$GITHUB_OUTPUT"'},
        ]}}}))
        calculator = self.src / "scripts/ci/utils/compute_partitions.py"
        calculator.parent.mkdir(parents=True)
        calculator.write_text(
            "import json, sys\n"
            "assert sys.argv[1:] == ['--output-format', 'json', '--pr-test-yml', "
            "'.github/workflows/pr-test.yml', '--full-parallel', 'true']\n"
            "print(json.dumps({'base-a-test-cpu': {'size': 3, 'arr': [0, 1, 2], 'max_parallel': 3}}))\n"
        )
        self.data = {
            "env": {"SGLANG_IS_IN_CI": True, "ADDED_WORKFLOW_FLAG": "workflow"},
            "jobs": {"run": {
                "timeout-minutes": 240,
                "env": {"ADDED_JOB_FLAG": "job"},
                "steps": [
                    {"uses": "actions/setup-python@v5", "with": {"python-version": "3.11"}},
                    {"uses": "actions/download-artifact@v4", "if": "${{ inputs.rust_ext_artifact != '' }}",
                     "continue-on-error": True},
                    {"run": "echo rust-from-checkout"},
                    {"run": 'echo "install-from-checkout $ADDED_WORKFLOW_FLAG $ADDED_JOB_FLAG $UV_SYSTEM_PYTHON"',
                     "env": {"UV_SYSTEM_PYTHON": "1"}},
                    {"timeout-minutes": "${{ fromJson(inputs.run_timeout_minutes) }}",
                     "env": {"CONTINUE_ON_ERROR_FLAG": "${{ fromJson(inputs.check_changes).continue_on_error == 'true' && '--continue-on-error' || '' }}",
                             "SGLANG_SKIP_RUST_TESTS": "${{ fromJson(inputs.check_changes).rust_workspace == 'true' && 'false' || 'true' }}"},
                     "run": 'cd test/\n# run_suite.py\n'
                            'echo "run-from-checkout ${{ inputs.self_name }} --auto-partition-id ${{ matrix.partition }}'
                            ' --auto-partition-size ${{ fromJson(inputs.partitions)[inputs.self_name].size }}'
                            ' --partition-model-file /tmp/partition-model.json --fork-worker-batch-size 20"\n'
                            'echo "$SGLANG_IS_IN_CI $SGLANG_SKIP_RUST_TESTS flag=[$CONTINUE_ON_ERROR_FLAG]"\nexit 7'},
                ],
            }},
        }

    def entry(self, *args):
        self.workflow.write_text(json.dumps(self.data))
        return subprocess.run(
            ["bash", str(ENTRY), *args], cwd=self.src, text=True,
            capture_output=True, env=dict(os.environ, CI_OUT=str(self.src)),
        )

    def test_plan_reuses_checkout_python(self):
        result = self.entry("plan")
        result.check_returncode()
        jobs, report = plan.normalize(json.loads(result.stdout))
        self.assertEqual([(job["id"], job["python"]) for job in jobs], [("cpu-unit-0", "3.11"), ("cpu-unit-1", "3.11"), ("cpu-unit-2", "3.11")])
        self.assertFalse(report)

    def test_run_uses_checkout_steps_and_propagates_suite_failure(self):
        result = self.entry("run", "cpu-unit-1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("install-from-checkout workflow job 1", result.stdout)
        self.assertEqual((self.src / "run-suite.log").read_text(),
                         "run-from-checkout base-a-test-cpu --auto-partition-id 1 --auto-partition-size 3 --partition-model-file /tmp/partition-model.json --fork-worker-batch-size 20\ntrue true flag=[]\n")

    def test_each_shard_uses_the_callers_run_timeout(self):
        caller = self.workflow.parent / "pr-test.yml"
        for minutes in ("7", "23"):
            with self.subTest(minutes=minutes):
                data = json.loads(caller.read_text())
                data["jobs"]["base-a-test-cpu"]["with"]["run_timeout_minutes"] = minutes
                caller.write_text(json.dumps(data))
                result = self.entry("plan")
                result.check_returncode()
                shards = json.loads(result.stdout)["jobs"]
                self.assertEqual([shard["run_timeout"] for shard in shards], [int(minutes)] * 3)

    def test_source_can_enable_continue_on_error(self):
        source = self.check_changes.read_text().replace("run_all_tests=false", "run_all_tests=true")
        self.check_changes.write_text(source)
        result = self.entry("run", "cpu-unit-1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("flag=[--continue-on-error]", (self.src / "run-suite.log").read_text())

    def test_step_environment_rejects_unknown_expression(self):
        self.data["jobs"]["run"]["steps"][1]["env"] = {"OTHER": "${{ unknown.context }}"}
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported workflow expression: unknown.context", result.stderr)

    def test_missing_suite_fails_plan(self):
        self.data["jobs"]["run"]["steps"].pop()
        result = self.entry("plan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no supported test entry", result.stderr)
