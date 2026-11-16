"""调度器：HTTP 服务 + 任务队列 + worker 注册表（纯标准库）。

HTTP 接口：

  POST /tasks                    提交任务，body {"command": "..."}
  GET  /tasks                    任务列表
  GET  /tasks/<id>               单个任务的状态与结果
  POST /workers/register         worker 注册，body {"name": "...", "labels": [...]}
  POST /workers/<id>/heartbeat   刷新 worker 存活时间
  GET  /workers                  在线 worker 列表
  POST /workers/<id>/next        worker 拉取下一个待派任务（无则返回 204）
  POST /tasks/<id>/result        worker 回传结果，body {"status": "...", "output": "..."}

worker 采用拉取模型：空闲时向调度器请求下一个任务，跑完回传结果。这样调度器无需
主动连接 worker，worker 之间也完全解耦。
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .task import Task, TaskStatus, WorkerInfo

# worker 超过该秒数没心跳即视为离线
WORKER_TTL_SECONDS = 30


class Scheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._queue: deque[str] = deque()  # 待派任务 id（FIFO）
        self._workers: dict[str, WorkerInfo] = {}

    # ---- 任务 ----

    def submit(self, command: str) -> Task:
        task = Task(command=command)
        with self._lock:
            self._tasks[task.id] = task
            self._queue.append(task.id)
        return task

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [t.as_dict() for t in self._tasks.values()]

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.as_dict() if task else None

    def record_result(self, task_id: str, status: str, output: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = status
            task.output = output
            task.finished_at = time.time()
            return True

    # ---- worker ----

    def register(self, name: str, labels: list[str], address: str) -> WorkerInfo:
        info = WorkerInfo(name=name, labels=labels, address=address)
        with self._lock:
            self._workers[info.id] = info
        return info

    def heartbeat(self, worker_id: str) -> bool:
        with self._lock:
            info = self._workers.get(worker_id)
            if info is None:
                return False
            info.last_seen = time.time()
            return True

    def list_workers(self) -> list[dict]:
        now = time.time()
        with self._lock:
            out = []
            for info in self._workers.values():
                d = info.as_dict()
                d["online"] = (now - info.last_seen) <= WORKER_TTL_SECONDS
                out.append(d)
            return out

    def next_task(self, worker_id: str) -> dict | None:
        """把队列里最早的一个待派任务派给该 worker；无任务返回 None。"""
        with self._lock:
            info = self._workers.get(worker_id)
            if info is not None:
                info.last_seen = time.time()
            while self._queue:
                task_id = self._queue.popleft()
                task = self._tasks.get(task_id)
                if task is not None and task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.RUNNING
                    task.worker = worker_id
                    task.started_at = time.time()
                    return task.as_dict()
            return None


class _Handler(BaseHTTPRequestHandler):
    scheduler: Scheduler  # 由 run_scheduler 注入

    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _route(self) -> tuple[str, str, str | None]:
        parts = [p for p in self.path.split("/") if p]
        # parts 形如 ["tasks"] / ["tasks", "<id>"] / ["workers", "<id>", "next"]
        if parts and parts[0] == "tasks":
            if len(parts) == 1:
                return "tasks", "", None
            if len(parts) == 2:
                return "task", parts[1], None
            if len(parts) == 3 and parts[2] == "result":
                return "task_result", parts[1], None
        if parts and parts[0] == "workers":
            if len(parts) == 1:
                return "workers", "", None
            if len(parts) == 2 and parts[1] == "register":
                return "register", "", None
            if len(parts) == 2:
                return "heartbeat", parts[1], None
            if len(parts) == 3 and parts[2] == "next":
                return "next", parts[1], None
        return "not_found", "", None

    def do_POST(self):
        kind, arg, _ = self._route()
        body = self._read_json()
        s = self.scheduler
        if kind == "tasks":
            task = s.submit(body.get("command", ""))
            self._send(201, {"task_id": task.id})
        elif kind == "task_result":
            ok = s.record_result(
                arg, body.get("status", TaskStatus.FAILURE), body.get("output", "")
            )
            self._send(200 if ok else 404, {"ok": ok})
        elif kind == "register":
            info = s.register(
                body.get("name", ""), body.get("labels", []), body.get("address", "")
            )
            self._send(201, {"worker_id": info.id})
        elif kind == "heartbeat":
            self._send(200 if s.heartbeat(arg) else 404, {"ok": s.heartbeat(arg)})
        elif kind == "next":
            task = s.next_task(arg)
            if task is None:
                self._send(204, None)
            else:
                self._send(200, task)
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self):
        kind, arg, _ = self._route()
        s = self.scheduler
        if kind == "tasks":
            self._send(200, s.list_tasks())
        elif kind == "task":
            task = s.get_task(arg)
            self._send(200 if task else 404, task or {"error": "not found"})
        elif kind == "workers":
            self._send(200, s.list_workers())
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # 静默默认日志，避免刷屏
        pass


def run_scheduler(host: str = "0.0.0.0", port: int = 8080) -> None:
    scheduler = Scheduler()
    handler = type("BoundHandler", (_Handler,), {"scheduler": scheduler})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"scheduler listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
