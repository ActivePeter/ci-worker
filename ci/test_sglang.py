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
        self.data = {
            "env": {"SGLANG_IS_IN_CI": True, "ADDED_WORKFLOW_FLAG": "workflow"},
            "jobs": {"run": {
                "timeout-minutes": 240,
                "env": {"ADDED_JOB_FLAG": "job"},
                "steps": [
                    {"uses": "actions/setup-python@v5", "with": {"python-version": "3.11"}},
                    {"run": "echo rust-from-checkout"},
                    {"run": 'echo "install-from-checkout $ADDED_WORKFLOW_FLAG $ADDED_JOB_FLAG $UV_SYSTEM_PYTHON"',
                     "env": {"UV_SYSTEM_PYTHON": "1"}},
                    {"env": {"SGLANG_SKIP_RUST_TESTS": "${{ fromJson(inputs.check_changes).rust_workspace == 'true' && 'false' || 'true' }}"},
                     "run": 'cd test/\n# run_suite.py\n'
                            'echo "run-from-checkout ${{ inputs.self_name }} --auto-partition-id ${{ matrix.partition }}'
                            ' --auto-partition-size ${{ fromJson(inputs.partitions)[inputs.self_name].size }}'
                            ' --partition-model-file /tmp/partition-model.json --fork-worker-batch-size 20"\n'
                            'echo "$SGLANG_IS_IN_CI $SGLANG_SKIP_RUST_TESTS"\nexit 7'},
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
        self.assertEqual([(job["id"], job["python"]) for job in jobs], [("cpu-unit", "3.11")])
        self.assertFalse(report)

    def test_run_uses_checkout_steps_and_propagates_suite_failure(self):
        result = self.entry("run", "cpu-unit")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("install-from-checkout workflow job 1", result.stdout)
        self.assertEqual((self.src / "run-suite.log").read_text(),
                         "run-from-checkout base-a-test-cpu --fork-worker-batch-size 20\ntrue true\n")

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
