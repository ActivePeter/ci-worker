"""Check the SGLang legacy entry plan, profiles, and dependency resolution."""
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

    def run_entry(self, root, verb, **extra_env):
        env = os.environ.copy()
        env.pop("SGLANG_CI_PROFILE", None)
        env.pop("SGLANG_CI_BASE_REF", None)
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
            ("ppu15-0.5.21", PREFETCH_MARKER, SHA256_MARKER, "114", 4),
            ("ppu-0.5.17-beta", SHA256_MARKER, PREFETCH_MARKER, "64", 2),
        )
        for profile, marker, other_marker, count, deselected in cases:
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
                self.assertIn("CUDA_VISIBLE_DEVICES=unset\n", result.stdout)
                self.assertIn(f"pytest arg: --rootdir={root}\n", result.stdout)
                self.assertEqual(result.stdout.count("pytest arg: --deselect\n"), deselected)
                if profile == "ppu-0.5.17-beta":
                    self.assertIn(
                        f"pytest arg: {MEM_CACHE_TEST_DIR / 'test_umbp_store.py'}\n", result.stdout,
                    )

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
                    self.assertIn("For local runs only", result.stderr)

            result = self.run_entry(root, "run", SGLANG_CI_PROFILE="ppu15-0.5.21")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PR 落后 base 分支 ppu15-0.5.21，请 rebase", result.stderr)
            self.assertIn("test_0519_storage_codec_compat.py", result.stderr)

            result = self.run_entry(root, "run", SGLANG_CI_PROFILE="unknown")
            self.assertEqual(result.returncode, 2)
            self.assertIn("Invalid SGLANG_CI_PROFILE", result.stderr)

    def test_base_ref_selects_profile_without_consulting_markers(self):
        cases = (
            ("ppu15-0.5.21", SHA256_MARKER, PREFETCH_MARKER),
            ("ppu-0.5.17-beta", PREFETCH_MARKER, SHA256_MARKER),
        )
        for base, unrelated_marker, required_marker in cases:
            with self.subTest(base=base), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tests = root / MEM_CACHE_TEST_DIR
                tests.mkdir(parents=True)
                (tests / unrelated_marker).touch()

                result = self.run_entry(root, "run", SGLANG_CI_BASE_REF=base)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"PR 落后 base 分支 {base}，请 rebase", result.stderr)
                self.assertIn(f"  {MEM_CACHE_TEST_DIR / required_marker}\n", result.stderr)

                rejected = self.run_entry(root, "run", SGLANG_CI_BASE_REF="main")
                self.assertEqual(rejected.returncode, 2, rejected.stderr)
                self.assertIn("Unsupported SGLang CI base_ref 'main'", rejected.stderr)

    def test_missing_files_are_all_listed_with_the_rebase_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / MEM_CACHE_TEST_DIR
            tests.mkdir(parents=True)
            (tests / "test_decode_radix_lock_ref.py").touch()
            result = self.run_entry(root, "run", SGLANG_CI_BASE_REF="ppu-0.5.17-beta")
            self.assertEqual(result.returncode, 1, result.stderr)
            heading, *missing = result.stderr.splitlines()
            self.assertEqual(heading, "PR 落后 base 分支 ppu-0.5.17-beta，请 rebase")
            self.assertIn(f"  {MEM_CACHE_TEST_DIR / SHA256_MARKER}", missing)
            self.assertIn(f"  {MEM_CACHE_TEST_DIR / 'test_unified_radix_hicache_dispatch.py'}", missing)
            self.assertNotIn(f"  {MEM_CACHE_TEST_DIR / 'test_decode_radix_lock_ref.py'}", missing)

    def test_setup_reads_dependency_specs_before_installing(self):
        linux_torch = "torch==2.13.0 ; sys_platform == 'linux'"
        other_torch = "torch==2.11.0 ; sys_platform != 'linux'"
        cases = (
            (
                [linux_torch, other_torch, "transformers==5.12.1", "tokenizers==0.22.2", "xgrammar==0.2.7"],
                [linux_torch, other_torch, "transformers==5.12.1", "tokenizers==0.22.2", "xgrammar==0.2.7"],
                "",
            ),
            ("torch", [], "pyproject 里没有 torch 依赖声明"),
            ("transformers", [], "pyproject 里没有 transformers 依赖声明"),
            ("xgrammar", [], "pyproject 里没有 xgrammar 依赖声明"),
        )
        baseline = {"torch": "torch==2.11.0", "transformers": "transformers==5.12.1", "xgrammar": "xgrammar==0.2.1"}
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
                    if isinstance(dependencies, str):
                        dependencies = [spec for name, spec in baseline.items() if name != dependencies]
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
                        cpu_install, runtime_install = result.stdout.split("uv arg: pip\n")[1:]
                        self.assertIn("https://download.pytorch.org/whl/cpu", cpu_install)
                        for dependency in expected[:2]:
                            self.assertIn(f"uv arg: {dependency}\n", cpu_install)
                            self.assertNotIn(dependency, runtime_install)
                        for dependency in (*expected[2:], "datasets", "parameterized"):
                            self.assertIn(f"uv arg: {dependency}\n", runtime_install)
                        self.assertIn("sglang-constraints.txt", cpu_install)
                        self.assertIn("sglang-constraints.txt", runtime_install)
                    if diagnostic:
                        self.assertIn(diagnostic, result.stderr)
                    else:
                        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
