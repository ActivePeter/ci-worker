"""Post a commit status on the tested repository (stdlib only)."""
import json
import os
import sys
import urllib.request


def post(repo, sha, state, context, description, target_url=None):
    body = {"state": state, "context": context, "description": description[:140]}
    if target_url:
        body["target_url"] = target_url
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/statuses/{sha}",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "token " + os.environ["GIE_GIT_TOKEN"].strip(),
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()
    print(f"status {context}={state} on {repo}@{sha[:12]}: {description[:140]}")


def run_url():
    return "{}/{}/actions/runs/{}".format(os.environ["GITHUB_SERVER_URL"],
                                         os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"])


if __name__ == "__main__":
    repo, sha, state, context, description = sys.argv[1:6]
    post(repo, sha, state, context, description, run_url())
