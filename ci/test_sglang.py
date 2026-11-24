"""Check the sglang legacy default entry plan and job/guard contracts."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import plan

ENTRY = Path(__file__).parent / "defaults" / "sglang.sh"


class SglangEntryTests(unittest.TestCase):
    def test_plan_declares_single_python_312_cpu_job(self):
        raw = json.loads(subprocess.check_output(["bash", str(ENTRY.resolve()), "plan"]))
        jobs, report = plan.normalize(raw)
        self.assertFalse(report)
        self.assertEqual([j["id"] for j in jobs], ["cpu-unit"])
        self.assertEqual(jobs[0]["python"], "3.12")
        self.assertFalse(jobs[0]["rust_cache"])
        self.assertFalse(jobs[0]["go"])

    def test_unknown_job_is_rejected(self):
        for verb in ("setup", "run"):
            with self.subTest(verb=verb):
                res = subprocess.run(
                    ["bash", str(ENTRY.resolve()), verb, "unknown"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, 2)

    def test_missing_managed_confirm_fails_when_mixin_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mixin = root / "python/sglang/srt/mem_cache/unified_cache/managed_host_mixin.py"
            mixin.parent.mkdir(parents=True)
            mixin.write_text("# stub\n")
            res = subprocess.run(
                ["bash", str(ENTRY.resolve()), "run", "cpu-unit"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("test_managed_confirm.py is missing", res.stderr)


if __name__ == "__main__":
    unittest.main()
