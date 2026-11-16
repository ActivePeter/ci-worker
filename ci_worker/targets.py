"""每个被服务私有仓库的一份「目标」配置。

一个 Target 就是 poller/worker 围绕的元组：私有仓库名、回写用 context、派发事件
名，以及 worker 落地的 unit 命令序列（示例，非可跑等价物）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    repo: str            # 私有仓库 full name，如 goodputai/goodput-infer-ext
    context: str         # 回写 commit status 的 context
    event: str           # repository_dispatch 的 event_type
    steps: tuple[str, ...]  # worker 依次执行的 unit 命令（示例）

    @property
    def name(self) -> str:
        return self.repo.split("/", 1)[1]


TARGETS: dict[str, Target] = {
    "ext": Target(
        repo="goodputai/goodput-infer-ext",
        context="ci/public-worker/unit",
        event="run-ext-unit",
        steps=(
            "python3 -m pytest tests/unit",
            "cargo check --workspace",
        ),
    ),
    "test": Target(
        repo="goodputai/test",
        context="ci/public-worker/test-unit",
        event="run-test-unit",
        steps=(
            "python scripts/ci.py static",
            "python scripts/ci.py unit",
        ),
    ),
    "dynamo": Target(
        repo="goodputai/dynamo",
        context="ci/public-worker/dynamo-unit",
        event="run-dynamo-unit",
        steps=(
            "cargo test --locked -p rcommu-lite",
            "cargo test --locked -p kvbm-host --lib -- --test-threads=1",
        ),
    ),
}
