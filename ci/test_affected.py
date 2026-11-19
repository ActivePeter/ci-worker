import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import affected


class Affected(unittest.TestCase):
    def test_regular_pr_discovered_by_the_poll_still_uses_its_pinned_base(self):
        base, head = 'b' * 40, 'a' * 40
        self.assertEqual(affected.requested_base('repository_dispatch', 'poll', 'pr-42', head, base), base)
        self.assertIsNone(affected.requested_base('repository_dispatch', 'poll', 'pr-42', head, ''))
        self.assertIsNone(affected.requested_base('repository_dispatch', 'poll', 'pr-other', head, base))

    def test_pr_diff_uses_merge_base_and_full_run_has_no_base(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                return subprocess.check_output(['git', '-C', tmp, *args], text=True).strip()

            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (root / 'common').write_text('root')
            git('add', '.')
            git('commit', '-qm', 'common')
            git('checkout', '-qb', 'topic')
            (root / 'subject').write_text('topic')
            git('add', '.')
            git('commit', '-qm', 'topic')
            head = git('rev-parse', 'HEAD')
            git('checkout', '-q', 'main')
            (root / 'base-only').write_text('main')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            self.assertEqual(affected.changed_paths(root, base, head), (base, ['subject']))
            self.assertEqual(affected.changed_paths(root, None, head), (None, None))
            self.assertEqual(affected.changed_paths(root, '0' * 40, head), (None, None))

    def test_only_valid_artifact_for_this_fingerprint_and_workflow_can_omit_job(self):
        value, suite, head = 'a' * 64, 'cache', 'c' * 40
        artifact_name = f'verification-markers-{value}'
        jobs = [dict(id='rust-job', verification=dict(namespace='rust-verified-v1', suite=suite))]
        known = dict(successful=True, head='b' * 40, fingerprint=value, suite=suite, run_id=4, run_attempt=1)
        artifacts = [dict(id=8, name=artifact_name, workflow_run=dict(id=4, head_branch='main'))]

        def request(path, *, size=None):
            if path.startswith('actions/artifacts?'):
                return json.dumps(dict(artifacts=[a for a in artifacts if 'name='+a['name']+'&' in path])).encode()
            if path == 'actions/runs/4':
                return b'{"conclusion":"success","path":".github/workflows/run-test-unit.yml"}'
            self.assertEqual(path, 'actions/artifacts/8/zip')
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.writestr('cache/result.json', json.dumps(known))
            return buffer.getvalue()

        with patch.dict(affected.os.environ, GITHUB_REF_NAME='main', GITHUB_RUN_ID='5'):
            receipt = affected.find_markers(value, jobs, head, request)['rust-job']
            self.assertEqual(receipt['verified_run_id'], 4)
            self.assertEqual(receipt['head'], head)
            artifacts[0]['name'] = 'verification-markers'
            self.assertIn('rust-job', affected.find_markers(value, jobs, head, request))
            known['fingerprint'] = 'd' * 64
            self.assertEqual(affected.find_markers(value, jobs, head, request), {})
            known['fingerprint'] = value
            artifacts[0]['workflow_run']['head_branch'] = 'untrusted'
            self.assertEqual(affected.find_markers(value, jobs, head, request), {})

    def test_full_runs_changed_cases_and_unavailable_marker_storage_keep_jobs(self):
        jobs = [dict(id='rust-job', verification=dict(namespace='rust-verified-v1', suite='cache'))]

        def should_not_evaluate(_):
            self.fail('mandatory job attempted verification lookup')

        for selection, verify_always in (({'full': 'always-path'}, False),
                                         ({'mandatory': ['rust-job']}, False),
                                         ({}, True)):
            with self.subTest(selection=selection, verify_always=verify_always):
                self.assertEqual(affected.prune('.', jobs, 'c' * 40, selection, verify_always,
                                                evaluate=should_not_evaluate), (jobs, None, {}))

        def unavailable(*_):
            raise OSError('fixture storage unavailable')

        self.assertEqual(affected.prune('.', jobs, 'c' * 40, {}, False, evaluate=unavailable), (jobs, None, {}))
