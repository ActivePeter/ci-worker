"""Post a commit status on the tested repository (stdlib only)."""
import json
import os
import re
import sys
import urllib.request


def request(repo, path, *, body=None, timeout=30):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "token " + os.environ["GIE_GIT_TOKEN"].strip(),
                 "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout)


def post(repo, sha, state, context, description, target_url=None, *, timeout=30):
    body = {"state": state, "context": context, "description": description[:140]}
    if target_url:
        body["target_url"] = target_url
    with request(repo, f"statuses/{sha}", body=body, timeout=timeout) as response:
        response.read()
    print(f"status {context}={state} on {repo}@{sha[:12]}: {description[:140]}")


def supersede(repo, sha, context, *, polled=False):
    # A cancelled checkout of a mutable ref has no pinned SHA and never ran prepare.
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        print("cancelled before resolving a target SHA")
        return
    url = run_url()
    with request(repo, f"commits/{sha}/status", timeout=4) as response:
        current = next((row for row in json.load(response)["statuses"] if row["context"] == context), {})
    target = current.get("target_url")
    # poll can place a pending flag before this run resolves its checkout.
    queued = polled and not target and current.get("description") == "queued by poll"
    if current.get("state") == "pending" and (target == url or queued):
        post(repo, sha, "error", context, "superseded", url, timeout=4)
    else:
        print(f"skip superseded status on {repo}@{sha[:12]}: no pending status for this run")


def run_url():
    return "{}/{}/actions/runs/{}".format(os.environ["GITHUB_SERVER_URL"],
                                         os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"])


if __name__ == "__main__":
    if sys.argv[1] == "--superseded":
        supersede(*sys.argv[2:5], polled=os.environ.get("CI_POLLED_REQUEST") == "true")
    else:
        repo, sha, state, context, description = sys.argv[1:6]
        post(repo, sha, state, context, description, run_url())
