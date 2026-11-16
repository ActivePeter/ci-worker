"""任务与 worker 的数据模型。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass
class Task:
    command: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = TaskStatus.PENDING
    worker: str | None = None
    output: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "worker": self.worker,
            "output": self.output,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class WorkerInfo:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    labels: list[str] = field(default_factory=list)
    address: str = ""
    last_seen: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "labels": self.labels,
            "address": self.address,
            "last_seen": self.last_seen,
        }
