"""ci_worker — 简易的公开仓库替私有仓库跑 CI 的参考实现。

这是把本仓库里那套 GitHub Actions workflow（poll-*.yml + run-*-unit.yml）用
Python 重新表达的一版，作为设计参考/文档，不要求真跑通。三块职责一一对应：

  poller  ~ poll-*.yml        轮询私有仓库的 open PR + main，派发工作
  worker  ~ run-*-unit.yml    拉私有代码、跑一个 unit job、回写 commit status
  github  ~ 裸 REST + statuses 的最小封装（只用标准库 urllib，无第三方依赖）

私有代码绝不进入本公开仓库；运行时用 GIE_GIT_TOKEN（用户 gh 令牌）在 worker
里以 git insteadOf 方式 clone，跑完把 status 回写到私有仓库。
"""

__all__ = ["github", "targets", "poller", "worker"]
