"""执行节点：动态注册 → 周期心跳 → 拉任务 → 执行 → 回传结果。

一个 worker 进程就是一个独立节点，可起任意多个。启动时向调度器注册拿到
worker_id，后台线程每 HEARTBEAT_INTERVAL 秒心跳一次保持在线；主循环空闲时向
调度器要下一个任务，用 subprocess 执行命令，把成功/失败与输出回传。
"""

from __future__ import annotations

import subprocess
import threading
import time

from .client import request_json
from .task import TaskStatus

HEARTBEAT_INTERVAL = 10  # 秒
IDLE_POLL_INTERVAL = 2   # 秒，空闲时多久问一次调度器


class Worker:
    def __init__(self, scheduler_url: str, name: str, labels: list[str] | None = None) -> None:
        self.base = scheduler_url.rstrip("/")
        self.name = name
        self.labels = labels or []
        self.worker_id: str | None = None

    def register(self) -> str:
        status, body = request_json(
            "POST", f"{self.base}/workers/register",
            {"name": self.name, "labels": self.labels},
        )
        if status != 201:
            raise RuntimeError(f"register failed: {status} {body}")
        self.worker_id = body["worker_id"]
        return self.worker_id

    def _heartbeat_loop(self) -> None:
        while True:
            request_json("POST", f"{self.base}/workers/{self.worker_id}/heartbeat")
            time.sleep(HEARTBEAT_INTERVAL)

    def _run_command(self, command: str, timeout: int = 3600) -> tuple[str, str]:
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout,
            )
            status = TaskStatus.SUCCESS if proc.returncode == 0 else TaskStatus.FAILURE
            output = (proc.stdout or "") + (proc.stderr or "")
            return status, output
        except subprocess.TimeoutExpired as exc:
            return TaskStatus.FAILURE, f"timeout: {exc}"

    def run(self, timeout: int = 3600) -> None:
        self.register()
        print(f"worker {self.name} registered as {self.worker_id}")
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

        while True:
            status, task = request_json(
                "POST", f"{self.base}/workers/{self.worker_id}/next"
            )
            if status == 204 or task is None:
                time.sleep(IDLE_POLL_INTERVAL)
                continue

            print(f"[{self.name}] running {task['id']}: {task['command']}")
            result, output = self._run_command(task["command"], timeout=timeout)
            request_json(
                "POST", f"{self.base}/tasks/{task['id']}/result",
                {"status": result, "output": output},
            )
            print(f"[{self.name}] finished {task['id']}: {result}")
