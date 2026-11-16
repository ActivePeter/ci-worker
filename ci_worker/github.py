"""最小 GitHub REST 客户端（标准库 urllib，无第三方依赖）。

只覆盖 ci_worker 需要的几个端点：open PR 的 head SHA、HEAD SHA、commit status
查询/写入、repository_dispatch。故意不引入 requests，保持零依赖、易读。
"""

from __future__ import annotations

import json
import urllib.request

API = "https://api.github.com"


class GitHubError(RuntimeError):
    """GitHub API 返回非 2xx。"""


class GitHub:
    def __init__(self, token: str, api: str = API) -> None:
        self.token = token.strip()
        self.api = api.rstrip("/")

    def _request(self, method: str, path: str, body: dict | None = None):
        data = None
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.api}{path}", data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
        # urlopen 对非 2xx 抛 HTTPError；这里统一兜底
        return json.loads(raw) if raw else None

    # ---- 只读 ----

    def head_sha(self, repo: str, ref: str = "main") -> str:
        """返回 repo 的 ref（分支/标签/SHA）对应的 commit SHA。"""
        return self._request("GET", f"/repos/{repo}/commits/{ref}")["sha"]

    def open_pr_head_shas(self, repo: str, non_fork_only: bool = True) -> list[str]:
        """返回 open PR 的 head SHA；默认只保留同仓库分支（跳过 fork）。"""
        prs = self._request("GET", f"/repos/{repo}/pulls?state=open&per_page=100")
        out = []
        for pr in prs:
            if non_fork_only and pr["head"]["repo"]["full_name"] != repo:
                continue
            out.append(pr["head"]["sha"])
        return out

    def latest_status(self, repo: str, ref: str, context: str) -> str | None:
        """返回某 ref 上指定 context 的最新 status state；无则 None。"""
        body = self._request("GET", f"/repos/{repo}/commits/{ref}/status")
        matched = [s for s in body.get("statuses", []) if s["context"] == context]
        if not matched:
            return None
        latest = sorted(matched, key=lambda s: s["updated_at"])[-1]
        return latest["state"]

    # ---- 写入 ----

    def create_status(
        self,
        repo: str,
        ref: str,
        context: str,
        state: str,
        description: str,
        target_url: str | None = None,
    ) -> None:
        self._request(
            "POST",
            f"/repos/{repo}/statuses/{ref}",
            {
                "state": state,
                "context": context,
                "description": description,
                "target_url": target_url,
            },
        )

    def dispatch(self, worker_repo: str, event_type: str, client_payload: dict) -> None:
        self._request(
            "POST",
            f"/repos/{worker_repo}/dispatches",
            {"event_type": event_type, "client_payload": client_payload},
        )
