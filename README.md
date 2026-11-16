# ci-worker

Public CI worker: runs a CI command on behalf of **goodputai private** repos, to
use public repos' free GitHub-hosted Actions minutes (team-plan private repos
are capped at 2000 min/month; public repos are not).

## How it keeps private code private

- Only `README.md` and `.github/workflows/run-ci.yml` live in this repo. Nothing
  private is ever committed or pushed here.
- The workflow clones the private repo **at runtime** using the repo secret
  `GIE_GIT_TOKEN` (the user's read-capable token), via a git `insteadOf` rewrite
  that is masked from logs and never written to disk.
- The token is the user's full-scope `gh` token (`repo` scope). It is broader
  than needed. Future hardening: swap for a fine-grained PAT limited to
  `Contents: read` on the target repos.

## Run it manually

1. Go to **Actions → run-ci-for-private-repo → Run workflow**.
2. Set `target_repo` (e.g. `goodputai/dynamo`), `ref` (default `main`), and
   `run` (the shell command to execute, default `git rev-parse HEAD`).
3. The result is reported back to the private repo as a commit status
   `ci/public-worker`.

## Trigger from a private repo (repository_dispatch)

From a private repo that has a token with write access to this repo:

```bash
curl -X POST https://api.github.com/repos/goodputai/ci-worker/dispatches \
  -H "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"event_type":"run-ci","client_payload":{"target_repo":"goodputai/dynamo","ref":"main","run":"git rev-parse HEAD"}}'
```

## Security notes

- Never add a `pull_request_target` trigger: it would expose `GIE_GIT_TOKEN`
  to pull requests from forks.
- `run` is arbitrary shell, executed in a trusted (org-only) context. Only
  org members with write access can trigger `workflow_dispatch` /
  `repository_dispatch`.
- The `GIE_GIT_TOKEN` here is the same secret name used by goodputai's other
  repos (see the `private-repo-deps` skill / `vibe-ci` secrets catalog).
