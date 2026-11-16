"""worker：拉私有代码、跑一个 unit job、回写 commit status。

对应 run-*-unit.yml。私有仓库通过 GIE_GIT_TOKEN 以 git insteadOf 方式 clone
（token 只进 git 配置、不进命令行、不打印），跑完无论成败都把 status 回写到私有
仓库（context 见 Target.context），target_url 指向本次运行的日志页。
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile

from .github import GitHub
from .targets import Target

log = logging.getLogger("ci_worker.worker")


def clone_via_token(repo: str, ref: str, dest: str, token: str) -> None:
    """用 token 做 insteadOf 改写后 clone；不把 token 写进命令行/日志。"""
    url = f"https://github.com/{repo}"
    auth_url = f"https://x-access-token:{token}@github.com/{repo}"
    subprocess.run(
        ["git", "config", "--global", f"url.{auth_url}.insteadOf", url],
        check=True,
    )
    subprocess.run(["git", "clone", "--no-checkout", url, dest], check=True)
    subprocess.run(["git", "-C", dest, "checkout", "--detach", ref], check=True)


def run_step(step: str, cwd: str) -> None:
    subprocess.run(step, shell=True, cwd=cwd, check=True)


def run(target: Target, ref: str, gh: GitHub, token: str, log_url: str | None = None) -> str:
    """跑一个 ref 的 unit job，返回 'success' | 'failure'，并回写 status。"""
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, target.name)
        clone_via_token(target.repo, ref, dest, token)
        head = subprocess.run(
            ["git", "-C", dest, "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        gh.create_status(target.repo, head, target.context, "pending",
                         f"public CI {target.name} unit running")

        state = "success"
        try:
            for step in target.steps:
                run_step(step, cwd=dest)
        except subprocess.CalledProcessError as exc:
            log.error("step failed for %s: %s", ref, exc)
            state = "failure"

        gh.create_status(
            target.repo, head, target.context, state,
            f"public CI {target.name} unit {state}", target_url=log_url,
        )
        return state
