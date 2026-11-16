"""轮询：扫私有仓库的 open PR + main，给没跑过的 ref 派发工作。

对应 poll-*.yml。语义是 run-once-per-SHA：只要某 ref 已经有过对应 context 的
status（success/pending/failure 都算），就跳过——这样既不会重复入队，也不会对
「确定性失败的 ref」每 5 分钟无限重试。派发前先把 context 置 pending，防止下一轮
重复派发。
"""

from __future__ import annotations

import logging

from .github import GitHub
from .targets import Target

log = logging.getLogger("ci_worker.poller")


def poll(target: Target, worker_repo: str, gh: GitHub, only_ref: str | None = None) -> int:
    """返回本轮实际派发的 ref 数量。"""
    if only_ref:
        refs = [only_ref]
    else:
        refs = gh.open_pr_head_shas(target.repo) + [gh.head_sha(target.repo)]
        # 去重、去空，保持稳定顺序
        refs = sorted({r for r in refs if r})

    dispatched = 0
    for ref in refs:
        state = gh.latest_status(target.repo, ref, target.context)
        if state is not None:
            log.info("skip %s (latest=%s)", ref, state)
            continue

        log.info("queue %s (no status yet)", ref)
        gh.create_status(target.repo, ref, target.context, "pending", "queued by poll")
        gh.dispatch(worker_repo, target.event, {"ref": ref, "source": "poll"})
        dispatched += 1

    log.info("poll %s dispatched=%d", target.name, dispatched)
    return dispatched
