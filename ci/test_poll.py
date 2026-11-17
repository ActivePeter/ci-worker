"""An idle repository must not fail polling before callers can poll its default branch."""
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


if __name__ == '__main__':
    unittest.main()
