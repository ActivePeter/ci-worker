"""An idle repository must not fail polling before callers can poll its default branch."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

POLL = Path(__file__).parent / 'poll.sh'


class PollTests(unittest.TestCase):
    def test_no_open_prs_or_protected_branches_is_success(self):
        with tempfile.TemporaryDirectory() as directory:
            curl = Path(directory) / 'curl'
            curl.write_text("#!/bin/sh\nprintf '[]\\n'\n")
            curl.chmod(0o755)
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'], GIE_GIT_TOKEN='test-token')
            result = subprocess.run(['bash', str(POLL.resolve()), 'example/idle', 'test/context', 'run-test'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('dispatched=0', result.stdout)


    def test_only_a_unique_pr_base_is_sent_for_affected_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = root / 'payloads.jsonl'
            curl = root / 'curl'
            curl.write_text("""#!/usr/bin/python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://api.github.com/'))
if '/pulls?' in url:
    def pr(n, head, base):
        return dict(number=n, head=dict(sha=head, repo=dict(full_name='example/repo')),
                    base=dict(sha=base))
    print(json.dumps([pr(1, 'a'*40, '1'*40), pr(2, 'b'*40, '1'*40),
                      pr(3, 'b'*40, '2'*40), pr(4, 'c'*40, '2'*40)]))
elif '/branches?' in url:
    print(json.dumps([dict(name='main', commit=dict(sha='c'*40))]))
elif url.endswith('/dispatches'):
    with Path(os.environ['POLL_PAYLOADS']).open('a') as stream:
        print(args[args.index('-d') + 1], file=stream)
else:
    print('{}')
""")
            curl.chmod(0o755)
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'], GIE_GIT_TOKEN='test-token',
                       POLL_PAYLOADS=str(payloads))
            subprocess.run(['bash', str(POLL.resolve()), 'example/repo', 'test/context', 'run-test'],
                           env=env, capture_output=True, text=True, check=True)
            rows = [json.loads(line)['client_payload'] for line in payloads.read_text().splitlines()]
            refs = {row['ref']: row for row in rows}
            self.assertEqual(len(rows), 3)
            self.assertEqual(refs['a'*40]['base'], '1'*40)
            self.assertEqual(refs['b'*40]['base'], '')
            self.assertEqual(refs['c'*40]['base'], '')
            self.assertEqual(refs['c'*40]['group'], 'branch-main')


if __name__ == '__main__':
    unittest.main()
