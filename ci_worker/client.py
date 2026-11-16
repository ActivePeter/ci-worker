"""HTTP 客户端：提交/查询任务，以及供 worker 复用的底层请求函数。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def request_json(method: str, url: str, body: dict | None = None) -> tuple[int, dict | None]:
    """发一个 JSON 请求，返回 (状态码, 解析后的 body 或 None)。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        # 204 / 404 等都走这里，尽量读回 body
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw else None)


class Client:
    """面向调度器的轻量客户端，用于提交与查询任务。"""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def submit(self, command: str) -> str:
        status, body = request_json("POST", f"{self.base}/tasks", {"command": command})
        if status != 201:
            raise RuntimeError(f"submit failed: {status} {body}")
        return body["task_id"]

    def list_tasks(self) -> list[dict]:
        _, body = request_json("GET", f"{self.base}/tasks")
        return body or []

    def get_task(self, task_id: str) -> dict | None:
        status, body = request_json("GET", f"{self.base}/tasks/{task_id}")
        return body if status == 200 else None

    def list_workers(self) -> list[dict]:
        _, body = request_json("GET", f"{self.base}/workers")
        return body or []
