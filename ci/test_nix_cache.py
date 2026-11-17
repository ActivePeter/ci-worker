"""Cache policy gates; the real-store corruption contract runs separately in CI."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import nix_cache


class CachePolicy(unittest.TestCase):
    def call(self, fn, **environment):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, environment), contextlib.redirect_stdout(io.StringIO()) as output:
            fn(Path(tmp), Path(tmp))
            return json.loads(output.getvalue().splitlines()[-1])

    def test_pr_cannot_write_even_when_dispatched_from_main(self):
        with patch.object(nix_cache.subprocess, 'run') as run:
            result = self.call(nix_cache.freeze, GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='pull_request', CI_JOB='static')
        self.assertEqual(result['save'], 'false')
        run.assert_not_called()

    def test_branch_and_non_static_jobs_are_read_only(self):
        for ref, job in [('refs/heads/feature', 'static'), ('refs/heads/main', 'unit-0')]:
            result = self.call(nix_cache.freeze, GITHUB_REF=ref, GITHUB_EVENT_NAME='workflow_dispatch', CI_JOB=job)
            self.assertEqual(result['save'], 'false')

    def test_self_hosted_store_is_never_restored(self):
        with patch.object(nix_cache.subprocess, 'run') as run:
            result = self.call(nix_cache.select, RUNNER_ENVIRONMENT='self-hosted')
        self.assertEqual(result['store_key'], '')
        run.assert_not_called()

    def test_dependency_gate_invokes_existing_frozen_manifest_verifier(self):
        from unittest.mock import Mock
        closure = Mock()
        value = {'manifest': {'frozen': 'dependency hashes'}}
        nix_cache.verify(value, closure, store='/isolated')
        closure.verify.assert_called_once_with(value['manifest'], store='/isolated')

    def test_keys_include_platform_lock_and_full_frozen_manifest_hash(self):
        with patch.dict(os.environ, RUNNER_OS='Linux', RUNNER_ARCH='X64'), patch.object(nix_cache, 'inputs', return_value={'flake.lock': 'lock-hash'}):
            key = nix_cache.store_key(Path('.'), 'closure-fingerprint')
        self.assertEqual(key, 'testkit-nix-store-v2-Linux-X64-lock-hash-closure-fingerprint')

    def test_main_history_accepts_merged_sha_and_rejects_pr_or_missing_ref(self):
        from types import SimpleNamespace
        environment = dict(GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='workflow_dispatch',
                           CI_JOB='static', CI_REF_SHA='pinned-main-history-sha')
        for rc, expected in ((0, True), (1, False), (128, False)):
            with patch.dict(os.environ, environment), patch.object(nix_cache.subprocess, 'run', return_value=SimpleNamespace(returncode=rc)) as run:
                self.assertEqual(nix_cache.writer_allowed(Path('.')), expected)
                self.assertEqual(run.call_args.args[0], ['git', 'merge-base', '--is-ancestor', 'pinned-main-history-sha', 'refs/remotes/origin/main'])

    def test_restored_store_uses_recorded_payload_without_any_home_profile(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        binary = Path('/nix/store/' + 'a' * 32 + '-nix-2.35.6/bin/nix')
        closure = SimpleNamespace(store_path=Mock())
        record = dict(path=str(binary), sha256=__import__('hashlib').sha256(b'payload').hexdigest())
        files = {binary, binary.with_name('nix-store')}
        with patch.object(Path, 'home', side_effect=AssertionError('HOME must not be consulted')), patch.object(Path, 'is_file', lambda path: path in files), patch.object(Path, 'read_bytes', return_value=b'payload'), patch.object(os, 'access', lambda path, mode: path in files):
            self.assertEqual(nix_cache.bind_nix(closure, record), binary)
        closure.store_path.assert_called_once_with(str(binary.parent.parent))
        self.assertEqual(closure.NIX_STORE, str(binary.with_name('nix-store')))

    def test_cached_bootstrap_corruption_never_falls_back_to_another_binary(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        binary = Path('/nix/store/' + 'a' * 32 + '-nix-2.35.6/bin/nix')
        record = dict(path=str(binary), sha256='0' * 64)
        with patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'read_bytes', return_value=b'corrupt'), patch.object(os, 'access', return_value=True):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                nix_cache.bind_nix(SimpleNamespace(store_path=Mock()), record)

    def test_default_main_cannot_save_a_pr_sha(self):
        from types import SimpleNamespace
        with patch.object(nix_cache.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            result = self.call(nix_cache.freeze, GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='workflow_dispatch', CI_JOB='static', CI_REF_SHA='pr-sha')
        self.assertEqual(result['save'], 'false')
        self.assertIn('target main history', result['reason'])


if __name__ == '__main__':
    unittest.main()
