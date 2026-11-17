"""Execute the worker selector against isolated target/fallback entry fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import report

ROOT = Path(__file__).resolve().parents[1]


class EntryControl(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'public-unit.sh'
        self.target.write_text("""#!/bin/bash
/usr/bin/python3 -I - "$@" <<'PY_TARGET'
import json, os, sys
print(json.dumps(dict(mode=os.environ.get('TEST_UNIT_SETUP', 'legacy'),
                     argv=sys.argv[1:], sha=os.environ.get('CI_REF_SHA'),
                     ci_job=os.environ.get('CI_JOB'), poison=os.environ.get('PYTHONHOME'))))
PY_TARGET
""")
        self.env = dict(os.environ, PATH='/usr/bin:/bin', ENTRY=str(self.target),
                        CI_ENTRY_KIND='target', CI_OUT=str(self.root / 'out'),
                        RUNNER_TEMP=str(self.root), CI_JOB='unit-2', CI_REF_SHA='frozen-sha',
                        TEST_UNIT_POISON_HOST='0')
        for name in ('TEST_UNIT_SETUP', 'PYTHONHOME', 'PYTHONPATH'):
            self.env.pop(name, None)

    def call(self, *args, **environment):
        return subprocess.run(['/bin/bash', str(ROOT / 'ci/entry.sh'), *args],
                              cwd=self.root, env=dict(self.env, **environment),
                              capture_output=True, text=True, timeout=10)

    def support_nix(self):
        (self.root / 'nix').mkdir()
        (self.root / 'nix/ci.sh').write_text('# target-owned environment fixture\n')

    def test_default_and_selected_modes_reach_setup_run_and_report(self):
        self.support_nix()
        for mode in (None, 'legacy', 'nix'):
            for phase in ('setup', 'run', 'report'):
                with self.subTest(mode=mode, phase=phase):
                    env = {} if mode is None else dict(TEST_UNIT_SETUP=mode)
                    child = self.call(phase, 'unit-2', **env)
                    self.assertEqual(child.returncode, 0, child.stderr)
                    value = json.loads(child.stdout)
                    self.assertEqual(value['mode'], mode or 'legacy')
                    self.assertEqual(value['argv'], [phase, 'unit-2'])
                    self.assertEqual((value['sha'], value['ci_job']), ('frozen-sha', 'unit-2'))

    def test_unknown_mode_fails_before_target_execution(self):
        self.target.write_text('exit 91\n')
        child = self.call('setup', TEST_UNIT_SETUP='unknown')
        self.assertEqual(child.returncode, 2)
        self.assertIn('unknown TEST_UNIT_SETUP', child.stderr)

    def test_nix_requires_a_supported_target_instead_of_falling_back(self):
        for kind in ('legacy', 'target'):
            with self.subTest(kind=kind):
                child = self.call('setup', TEST_UNIT_SETUP='nix', CI_ENTRY_KIND=kind)
                self.assertEqual(child.returncode, 2)
                self.assertIn('legacy fallback cannot run Nix', child.stderr)
        self.support_nix()
        child = self.call('report', TEST_UNIT_SETUP='nix', CI_ENTRY_KIND='legacy')
        self.assertEqual(child.returncode, 2)

    def test_legacy_fallback_prepares_original_environment_and_rejects_nix(self):
        binary = self.root / 'bin'; binary.mkdir()
        trace = self.root / 'python-args'
        python = binary / 'python3'
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$TRACE"\n')
        python.chmod(0o755)
        env = dict(self.env, PATH=str(binary) + ':/usr/bin:/bin', TRACE=str(trace))
        fallback = ROOT / 'ci/defaults/test.sh'
        child = subprocess.run(['/bin/bash', str(fallback), 'setup', 'static'],
                               cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(trace.read_text().strip(),
                         'testkit env prepare --uv uv --cache-config config/cache-ephemeral.json --export-github')
        trace.unlink()
        for phase in ('plan', 'setup', 'run', 'report'):
            with self.subTest(phase=phase):
                child = subprocess.run(['/bin/bash', str(fallback), phase, 'static'],
                                       cwd=self.root, env=dict(env, TEST_UNIT_SETUP='nix'),
                                       capture_output=True, text=True, timeout=10)
                self.assertEqual(child.returncode, 2)
                self.assertIn('only supports TEST_UNIT_SETUP=legacy', child.stderr)
        self.assertFalse(trace.exists())

    def test_host_poison_is_real_and_stays_in_target_child(self):
        binary = self.root / 'host-bin'; binary.mkdir()
        for name in ('rustc', 'python', 'python3'):
            path = binary / name; path.write_text('#!/bin/sh\nexit 0\n'); path.chmod(0o755)
        self.env['PATH'] = str(binary) + ':/usr/bin:/bin'
        self.env['GITHUB_ENV'] = str(self.root / 'github-env')
        Path(self.env['GITHUB_ENV']).write_text('UNCHANGED=yes\n')
        self.target.write_text('python3 --version\n')
        clean = self.call('setup', TEST_UNIT_SETUP='legacy')
        poisoned = self.call('setup', TEST_UNIT_SETUP='legacy', TEST_UNIT_POISON_HOST='1')
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(poisoned.returncode, 93)
        self.assertIn('host Python was deliberately replaced', poisoned.stderr)
        self.assertEqual((self.root / 'out/host-poison.txt').read_text(),
                         'rustc absent; host Python exits 93\n')
        self.support_nix()
        self.target.write_text("""if command -v rustc; then exit 92; fi
if python3 --version; then exit 91; else [ "$?" = 93 ] || exit 90; fi
/usr/bin/python3 -I -c 'print("isolated control Python still works")'
""")
        child = self.call('report', TEST_UNIT_SETUP='nix', TEST_UNIT_POISON_HOST='1')
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn('isolated control Python still works', child.stdout)
        self.assertEqual(Path(self.env['GITHUB_ENV']).read_text(), 'UNCHANGED=yes\n')
        # The worker never installs or enters Nix; the supported target owns that.


class FinalReport(unittest.TestCase):
    def test_required_report_missing_is_red_and_success_remains_single_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root / 'job-static'; job.mkdir()
            (job / '.ci-job-status').write_text('success')
            env = dict(REPO='fixture/test', CONTEXT='fixture-context', SHA='exact-sha',
                       KIND='target', JOBS=json.dumps([dict(id='static')]),
                       PREPARE_RESULT='success', CI_IN=str(root),
                       GITHUB_SERVER_URL='https://github.com', GITHUB_REPOSITORY='fixture/worker',
                       GITHUB_RUN_ID='fixture-run')
            for rc, expected in [('missing', 1), ('1', 1), ('0', 0)]:
                with self.subTest(report_rc=rc), patch.dict(os.environ, dict(env, REPORT_RC=rc), clear=True), patch.object(report.status, 'post') as post:
                    self.assertEqual(report.main(), expected)
                    post.assert_called_once()
                    self.assertEqual(post.call_args.args[0:4],
                                     ('fixture/test', 'exact-sha', 'failure' if expected else 'success', 'fixture-context'))


if __name__ == '__main__':
    unittest.main()
