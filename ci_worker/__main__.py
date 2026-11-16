"""命令行入口：`python -m ci_worker poll|run`。

用法（示例，非可跑等价物）：
  python -m ci_worker poll --target ext
  python -m ci_worker run  --target ext --ref <sha-or-branch>

令牌取自环境变量 GIE_GIT_TOKEN；worker_repo 默认 ActivePeter/ci-worker。
"""

from __future__ import annotations

import argparse
import logging
import os

from .github import GitHub
from .poller import poll
from .targets import TARGETS
from .worker import run

DEFAULT_WORKER_REPO = "ActivePeter/ci-worker"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ci_worker")
    ap.add_argument("--token", default=os.environ.get("GIE_GIT_TOKEN", ""))
    ap.add_argument("--worker-repo", default=DEFAULT_WORKER_REPO)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_poll = sub.add_parser("poll", help="轮询并派发工作")
    p_poll.add_argument("--target", required=True, choices=sorted(TARGETS))
    p_poll.add_argument("--only-ref", default=None)

    p_run = sub.add_parser("run", help="跑单个 ref 的 unit job")
    p_run.add_argument("--target", required=True, choices=sorted(TARGETS))
    p_run.add_argument("--ref", required=True)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    gh = GitHub(args.token)
    target = TARGETS[args.target]

    if args.cmd == "poll":
        poll(target, args.worker_repo, gh, only_ref=args.only_ref)
    else:
        run(target, args.ref, gh, args.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
