"""Check the sglang legacy default entry plan and job/guard contracts."""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import plan

ENTRY = Path(__file__).resolve().parent / "defaults" / "sglang.sh"
MEM_CACHE_TEST_DIR = Path("test/registered/unit/mem_cache")
PREFETCH_MARKER = "test_managed_prefetch_contract.py"
SHA256_MARKER = "test_managed_sha256.py"


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

    def run_entry(self, root, verb, **extra_env):
        env = os.environ.copy()
        env.pop("SGLANG_CI_PROFILE", None)
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(ENTRY), verb, "cpu-unit"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_profile_selects_the_checkout_cpu_list(self):
        listed_tests = set(
            re.findall(r"^  (test_\w+\.py)$", ENTRY.read_text(), re.MULTILINE)
        ) - {PREFETCH_MARKER, SHA256_MARKER}
        cases = (
            ("ppu15-0.5.21", PREFETCH_MARKER, SHA256_MARKER, "", "23"),
            ("ppu-0.5.17-beta", SHA256_MARKER, PREFETCH_MARKER, "unset", "61"),
        )
        for profile, marker, other_marker, cuda, count in cases:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tests = root / MEM_CACHE_TEST_DIR
                tests.mkdir(parents=True)
                for filename in listed_tests | {marker}:
                    (tests / filename).touch()
                python = root / "python3"
                python.write_text(
                    '#!/bin/bash\nprintf "CUDA_VISIBLE_DEVICES=%s\n" "${CUDA_VISIBLE_DEVICES-unset}"'
                    '\nprintf "pytest arg: %s\n" "$@"\n'
                )
                python.chmod(0o755)

                result = self.run_entry(root, "run", PATH=f"{root}:{os.environ['PATH']}")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    f"Running {count} sglang CPU unit test files (profile {profile})",
                    result.stdout,
                )
                self.assertIn(f"pytest arg: {MEM_CACHE_TEST_DIR / marker}\n", result.stdout)
                self.assertNotIn(other_marker, result.stdout)
                self.assertIn(f"CUDA_VISIBLE_DEVICES={cuda}\n", result.stdout)

    def test_profile_requires_a_unique_marker_without_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / MEM_CACHE_TEST_DIR
            tests.mkdir(parents=True)
            for filenames in ((), (PREFETCH_MARKER, SHA256_MARKER)):
                with self.subTest(filenames=filenames):
                    for filename in filenames:
                        (tests / filename).touch()
                    result = self.run_entry(root, "run")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Cannot identify SGLang CI profile", result.stderr)

            result = self.run_entry(root, "run", SGLANG_CI_PROFILE="ppu15-0.5.21")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ppu15-0.5.21 is missing required test file", result.stderr)
            self.assertIn("test_managed_confirm.py", result.stderr)

            result = self.run_entry(root, "run", SGLANG_CI_PROFILE="unknown")
            self.assertEqual(result.returncode, 2)
            self.assertIn("Invalid SGLANG_CI_PROFILE", result.stderr)

    def test_setup_reads_dependency_specs_before_installing(self):
        cases = (
            (
                ["transformers==5.12.1", "tokenizers==0.22.2", "xgrammar==0.2.7"],
                ["transformers==5.12.1", "tokenizers==0.22.2", "xgrammar==0.2.7", "datasets"],
                "",
            ),
            (
                ["transformers >= 5.0", "xgrammar==0.2.1"],
                ["transformers >= 5.0", "tokenizers", "xgrammar==0.2.1", "datasets"],
                "",
            ),
            (
                ["transformers==5.12.1"],
                ["transformers==5.12.1", "tokenizers", "xgrammar", "datasets"],
                "pyproject 里没有 xgrammar 依赖声明",
            ),
            (["transformers-extra"], [], "pyproject 里没有 transformers 依赖声明"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pyproject = root / "python/pyproject.toml"
            pyproject.parent.mkdir()
            for name in ("sudo", "uv"):
                command = root / name
                command.write_text(f'#!/bin/bash\nprintf "{name} arg: %s\n" "$@"\n')
                command.chmod(0o755)

            for dependencies, expected, diagnostic in cases:
                with self.subTest(dependencies=dependencies):
                    pyproject.write_text(
                        f"[project]\ndependencies = {json.dumps(dependencies)}\n",
                        encoding="utf-8",
                    )
                    result = self.run_entry(root, "setup", PATH=f"{root}:{os.environ['PATH']}")
                    if not expected:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, "")
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        for dependency in expected:
                            self.assertIn(f"uv arg: {dependency}\n", result.stdout)
                    if diagnostic:
                        self.assertIn(diagnostic, result.stderr)
                    else:
                        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
