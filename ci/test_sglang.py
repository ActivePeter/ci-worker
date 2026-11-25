"""The CPU bridge reads setup and test commands from the target stage."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import plan

ENTRY = Path(__file__).resolve().parent / "defaults" / "sglang.sh"


class SglangEntryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.src = Path(scratch.name)
        workflow = self.src / ".github/workflows/_pr-test-stage-cpu.yml"
        workflow.parent.mkdir(parents=True)
        (self.src / "test").mkdir()
        workflow.write_text(json.dumps({"env": {"SGLANG_IS_IN_CI": True, "USE_VENV": False}, "jobs": {"run": {
            "timeout-minutes": 240,
            "steps": [
                {"name": "Set up Python", "with": {"python-version": "3.11"}},
                {"name": "Install protoc + Rust toolchain", "run": "echo rust-from-checkout"},
                {"name": "Install dependencies", "env": {"UV_SYSTEM_PYTHON": "1"},
                 "run": 'echo "install-from-checkout UV_SYSTEM_PYTHON=$UV_SYSTEM_PYTHON"'},
                {"name": "Run test", "env": {"SGLANG_SKIP_RUST_TESTS": "${{ fixture }}"},
                 "run": 'cd test/\n'
                        'echo "run-from-checkout ${{ inputs.self_name }} --auto-partition-id ${{ matrix.partition }}'
                        ' --auto-partition-size ${{ fromJson(inputs.partitions)[inputs.self_name].size }}'
                        ' --partition-model-file /tmp/model.json --fork-worker-batch-size 20 $CONTINUE_ON_ERROR_FLAG"\n'
                        'echo "$SGLANG_IS_IN_CI $SGLANG_SKIP_RUST_TESTS"\nexit 7'},
            ],
        }}}))

    def entry(self, *args):
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

    def test_setup_uses_checkout_install_steps(self):
        result = self.entry("setup", "cpu-unit")
        result.check_returncode()
        self.assertEqual(result.stdout, "rust-from-checkout\ninstall-from-checkout UV_SYSTEM_PYTHON=1\n")

    def test_run_keeps_checkout_options_and_fails_with_the_suite(self):
        result = self.entry("run", "cpu-unit")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual((self.src / "run-suite.log").read_text(),
                         "run-from-checkout base-a-test-cpu --fork-worker-batch-size 20 --continue-on-error\ntrue true\n")
