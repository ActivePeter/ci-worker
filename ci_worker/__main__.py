"""命令行入口。

调度器：
  python -m ci_worker scheduler --host 0.0.0.0 --port 8080
worker（可开多个）：
  python -m ci_worker worker --scheduler http://127.0.0.1:8080 --name node1
提交 / 查询任务：
  python -m ci_worker submit --scheduler http://127.0.0.1:8080 --command "echo hi"
  python -m ci_worker tasks   --scheduler http://127.0.0.1:8080
  python -m ci_worker workers --scheduler http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse

from .client import Client
from .scheduler import run_scheduler
from .worker import Worker


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ci_worker")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sched = sub.add_parser("scheduler", help="启动调度器 HTTP 服务")
    sched.add_argument("--host", default="0.0.0.0")
    sched.add_argument("--port", type=int, default=8080)

    wk = sub.add_parser("worker", help="启动一个执行节点")
    wk.add_argument("--scheduler", default="http://127.0.0.1:8080")
    wk.add_argument("--name", default="node")
    wk.add_argument("--label", action="append", default=[])

    sub_ = sub.add_parser("submit", help="提交一个任务")
    sub_.add_argument("--scheduler", default="http://127.0.0.1:8080")
    sub_.add_argument("--command", required=True)

    tasks = sub.add_parser("tasks", help="列出任务")
    tasks.add_argument("--scheduler", default="http://127.0.0.1:8080")

    workers = sub.add_parser("workers", help="列出 worker")
    workers.add_argument("--scheduler", default="http://127.0.0.1:8080")

    args = ap.parse_args(argv)
    client = Client(args.scheduler)

    if args.cmd == "scheduler":
        run_scheduler(args.host, args.port)
    elif args.cmd == "worker":
        Worker(args.scheduler, args.name, args.label).run()
    elif args.cmd == "submit":
        task_id = client.submit(args.command)
        print(task_id)
    elif args.cmd == "tasks":
        for t in client.list_tasks():
            print(f"{t['id']:12} {t['status']:8} {t['worker'] or '-':10} {t['command']}")
    elif args.cmd == "workers":
        for w in client.list_workers():
            print(f"{w['id']:8} {w['name']:10} online={w['online']} {w['labels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
