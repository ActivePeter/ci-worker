"""Exercise poll selection and dispatch against fixture GitHub responses."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

POLL = Path(__file__).resolve().with_name("poll.sh")
REPO = "example/source"
TARGETS = "release/a,release/b"


def pull(number, base, repo=REPO):
    return {
        "number": number,
        "base": {"ref": base},
        "head": {"sha": f"p{number:03}", "repo": {"full_name": repo}},
    }


class PollTests(unittest.TestCase):
    def run_poll(self, responses, *, target_branches=None, only="", fail_dispatch=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "responses.json"
            fixture.write_text(json.dumps(responses))
            requests = root / "requests.jsonl"
            curl = root / "curl"
            curl.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
prefix = "https://api.github.com/"
endpoint = next(a.removeprefix(prefix) for a in args if a.startswith(prefix))
method = args[args.index("-X") + 1] if "-X" in args else "GET"
body = json.loads(args[args.index("-d") + 1]) if "-d" in args else None
with Path(os.environ["MOCK_REQUESTS"]).open("a") as log:
    log.write(json.dumps([method, endpoint, body]) + "\\n")
if method == "GET":
    responses = json.loads(Path(os.environ["MOCK_RESPONSES"]).read_text())
    response = responses[endpoint]
    status = 200
    if isinstance(response, dict) and "_fixture_status" in response:
        status = response["_fixture_status"]
        response = {}
    print(json.dumps(response))
    if "-w" in args:
        print(status)
elif endpoint.endswith("/dispatches") and os.environ["MOCK_FAIL_DISPATCH"] == "1":
    sys.exit(22)
"""
            )
            curl.chmod(0o755)
            env = dict(
                os.environ,
                PATH=f"{root}:{os.environ['PATH']}",
                GIE_GIT_TOKEN="test-token",
                MOCK_RESPONSES=str(fixture),
                MOCK_REQUESTS=str(requests),
                MOCK_FAIL_DISPATCH="1" if fail_dispatch else "0",
            )
            command = ["bash", str(POLL), REPO, "test/context", "run-test", only]
            if target_branches is not None:
                command.append(target_branches)
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            return result, [json.loads(line) for line in requests.read_text().splitlines()]

    def test_no_open_prs_or_protected_branches_is_success(self):
        result, _ = self.run_poll({
            f"repos/{REPO}/pulls?state=open&per_page=100": [],
            f"repos/{REPO}/branches?protected=true&per_page=100": [],
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dispatched=0", result.stdout)

    def test_whitelist_dispatches_both_branch_heads_and_only_matching_non_fork_prs(self):
        responses = {
            f"repos/{REPO}/pulls?state=open&per_page=100&page=1": [
                pull(1, "release/a"),
                pull(2, "main"),
                pull(3, "release/b"),
                pull(4, "release/a", "fork/source"),
            ],
            f"repos/{REPO}/branches/release%2Fa": {
                "name": "release/a", "protected": False, "commit": {"sha": "ba"},
            },
            f"repos/{REPO}/branches/release%2Fb": {
                "name": "release/b", "protected": False, "commit": {"sha": "bb"},
            },
        }
        expected = {
            "ba": "branch-release_a",
            "bb": "branch-release_b",
            "p001": "pr-1",
            "p003": "pr-3",
        }
        responses[f"repos/{REPO}/commits/main"] = {"sha": "p002"}
        rejected, _ = self.run_poll(responses, target_branches=TARGETS, only="main")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("is not a PR head or branch head", rejected.stderr)
        responses.update({f"repos/{REPO}/commits/{sha}/status": {"statuses": []} for sha in expected})
        result, requests = self.run_poll(responses, target_branches=TARGETS)
        self.assertEqual(result.returncode, 0, result.stderr)
        dispatches = [
            body["client_payload"]
            for method, endpoint, body in requests
            if method == "POST" and endpoint.endswith("/dispatches")
        ]
        self.assertEqual({payload["ref"]: payload["group"] for payload in dispatches}, expected)
        self.assertTrue(all(set(payload) == {"ref", "group", "source"} for payload in dispatches))
        self.assertIn("dispatched=4", result.stdout)

    def test_missing_target_branch_does_not_block_other_target(self):
        result, requests = self.run_poll({
            f"repos/{REPO}/pulls?state=open&per_page=100&page=1": [],
            f"repos/{REPO}/branches/release%2Fa": {"_fixture_status": 404},
            f"repos/{REPO}/branches/release%2Fb": {"name": "release/b", "commit": {"sha": "bb"}},
            f"repos/{REPO}/commits/bb/status": {"statuses": []},
        }, target_branches=TARGETS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning::target branch release/a was not found", result.stderr)
        self.assertEqual([body["client_payload"]["ref"] for method, endpoint, body in requests
                          if method == "POST" and endpoint.endswith("/dispatches")], ["bb"])

    def test_dispatch_failure_is_retried_without_requeuing_test_failures(self):
        responses = {
            f"repos/{REPO}/pulls?state=open&per_page=100&page=1": [pull(1, "release/a")],
            f"repos/{REPO}/branches/release%2Fa": {"name": "release/a", "commit": {"sha": "ba"}},
            f"repos/{REPO}/commits/ba/status": {"statuses": []},
            f"repos/{REPO}/commits/p001/status": {
                "statuses": [{"context": "test/context", "state": "failure", "description": "tests failed"}],
            },
        }
        failed, requests = self.run_poll(responses, target_branches="release/a", fail_dispatch=True)
        self.assertEqual(failed.returncode, 0, failed.stderr)
        self.assertIn("dispatch failed for ba", failed.stdout)
        statuses = [body for method, endpoint, body in requests
                    if method == "POST" and endpoint.endswith("/statuses/ba")]
        self.assertEqual([status["state"] for status in statuses], ["pending", "failure"])
        responses[f"repos/{REPO}/commits/ba/status"] = {"statuses": [statuses[-1]]}
        responses[f"repos/{REPO}/commits/ba"] = {"sha": "ba"}
        retried, requests = self.run_poll(responses, target_branches="release/a", only="ba")
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertIn("dispatched=1", retried.stdout)
        self.assertEqual([body["client_payload"]["ref"] for method, endpoint, body in requests
                          if method == "POST" and endpoint.endswith("/dispatches")], ["ba"])

    def test_without_whitelist_keeps_legacy_pr_and_protected_branch_selection(self):
        result, requests = self.run_poll({
            f"repos/{REPO}/pulls?state=open&per_page=100": [
                pull(1, "release/a"), pull(2, "main"), pull(3, "release/b", "fork/source"),
            ],
            f"repos/{REPO}/branches?protected=true&per_page=100": [
                {"name": "protected/legacy", "commit": {"sha": "legacy"}},
            ],
            f"repos/{REPO}/commits/legacy/status": {"statuses": []},
            f"repos/{REPO}/commits/p001/status": {"statuses": []},
            f"repos/{REPO}/commits/p002/status": {"statuses": []},
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [body["client_payload"]["ref"] for method, endpoint, body in requests
             if method == "POST" and endpoint.endswith("/dispatches")],
            ["legacy", "p001", "p002"],
        )
        self.assertIn("dispatched=3", result.stdout)

    def test_dispatch_without_whitelist_keeps_legacy_payload(self):
        result, requests = self.run_poll({
            f"repos/{REPO}/pulls?state=open&per_page=100": [pull(1, "release/a")],
            f"repos/{REPO}/branches?protected=true&per_page=100": [
                {"name": "protected/legacy", "commit": {"sha": "legacy"}},
            ],
            f"repos/{REPO}/commits/p001/status": {"statuses": []},
            f"repos/{REPO}/commits/legacy/status": {"statuses": []},
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [body for method, endpoint, body in requests
             if method == "POST" and endpoint.endswith("/dispatches")],
            [
                {"event_type": "run-test",
                 "client_payload": {"ref": "legacy", "group": "branch-protected_legacy", "source": "poll"}},
                {"event_type": "run-test",
                 "client_payload": {"ref": "p001", "group": "pr-1", "source": "poll"}},
            ],
        )

    def test_whitelist_checks_past_the_first_page_of_open_prs(self):
        result, _ = self.run_poll({
            f"repos/{REPO}/pulls?state=open&per_page=100&page=1": [pull(n, "main") for n in range(100)],
            f"repos/{REPO}/pulls?state=open&per_page=100&page=2": [pull(100, "release/a")],
            f"repos/{REPO}/branches/release%2Fa": {"name": "release/a", "commit": {"sha": "ba"}},
            f"repos/{REPO}/commits/ba/status": {"statuses": []},
            f"repos/{REPO}/commits/p100/status": {"statuses": []},
        }, target_branches="release/a")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("queue p100 pr-100", result.stdout)
        self.assertIn("dispatched=2", result.stdout)


if __name__ == "__main__":
    unittest.main()
