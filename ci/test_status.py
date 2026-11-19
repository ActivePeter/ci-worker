"""Prevent a cancelled run from stranding or overwriting a public commit status."""
import io
import json
import unittest
from unittest.mock import patch

import status


REPO = 'goodputai/test'
SHA = 'a' * 40
CONTEXT = 'ci/public-worker/test-unit'
URL = 'https://github.com/ActivePeter/ci-worker/actions/runs/123'


class SupersededStatus(unittest.TestCase):
    def check_status(self, rows, expected, *, polled=False, sha=SHA):
        calls = []

        def request(repo, path, *, body=None, timeout=30):
            calls.append((repo, path, body, timeout))
            return io.BytesIO(json.dumps({'statuses': rows}).encode())

        with patch.object(status, 'run_url', return_value=URL), patch.object(status, 'request', side_effect=request):
            status.supersede(REPO, sha, CONTEXT, polled=polled)
        if sha == SHA:
            self.assertEqual(calls[0], (REPO, f'commits/{SHA}/status', None, 4))
            calls = calls[1:]
        self.assertEqual(calls, expected)

    def test_own_pending_status_gets_one_error_with_the_run_link(self):
        row = dict(context=CONTEXT, state='pending', target_url=URL)
        self.check_status([row], [(REPO, f'statuses/{SHA}', dict(
            state='error', description='superseded', target_url=URL, context=CONTEXT), 4)])

    def test_pending_poll_before_prepare_gets_a_terminal_status(self):
        row = dict(context=CONTEXT, state='pending', description='queued by poll')
        self.check_status([row], [(REPO, f'statuses/{SHA}', dict(
            state='error', description='superseded', target_url=URL, context=CONTEXT), 4)], polled=True)
        self.check_status([row], [])

    def test_newer_or_terminal_status_and_an_unresolved_ref_are_preserved(self):
        for state, link in [('pending', URL + '4'), ('success', URL), ('failure', URL), ('error', URL)]:
            with self.subTest(state=state, link=link):
                self.check_status([dict(context=CONTEXT, state=state, target_url=link)], [])
        self.check_status([dict(context='other', state='pending', target_url=URL)], [])
        self.check_status([], [], sha='refs/heads/main')
