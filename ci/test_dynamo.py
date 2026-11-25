"""Check the contract dispatch against a workflow with the older pickq setup."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ENTRY = Path(__file__).resolve().parent / "defaults/dynamo.sh"


class DynamoWorkflowOrder(unittest.TestCase):
    def test_pickq_runs_the_declared_steps_without_release_only_setup(self):
        with tempfile.TemporaryDirectory() as root:
            checkout = Path(root)
            workflow = checkout / ".github/workflows/release-1.6.1-contracts.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(json.dumps({"jobs": {
                "cpu-contracts": {"timeout-minutes": 20, "steps": [
                    {"name": "Renamed Python prerequisite", "run": "echo cpu-install >> observed"},
                    {"name": "Older input suite", "run": "echo cpu-test >> observed"},
                ]},
                "rust-contracts": {"timeout-minutes": 90, "steps": [
                    {"name": "Renamed Rust prerequisite", "run": "echo rust-install >> observed"},
                    {"name": "Older contracts", "run": "echo .github/ci/run_rust_gate.py --label llm-unit >> observed\n"
                     "echo .github/ci/run_rust_gate.py --label llm-http-batch >> observed\n"
                     "echo .github/ci/run_rust_gate.py --label llm-http-nvext >> observed"},
                ]},
            }}))
            for job in ("cpu-contracts", "llm-http-nvext"):
                for phase in ("setup", "run"):
                    result = subprocess.run(["bash", str(ENTRY), phase, job], cwd=checkout,
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((checkout / "observed").read_text().splitlines(), [
                "cpu-install", "cpu-test", "rust-install",
                ".github/ci/run_rust_gate.py --label llm-http-nvext",
            ])
