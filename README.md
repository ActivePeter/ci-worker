# ci-worker

公开仓库替私有仓库（goodputai org）跑 CI，省 team 计划的 GitHub-hosted Actions 分钟。

## 现状：GitHub Actions 方案（正本，可用）

私有代码绝不进本公开仓库，只放 workflow。运行时用 `GIE_GIT_TOKEN`（用户 gh 令牌）
在 runner 里以 git `insteadOf` 方式 clone 私有仓库，跑完把 commit status 回写。

- `poll-<repo>.yml` — 每 5 分钟轮询私有仓库 open PR（非 fork）+ main，对没有 status 的
  ref 派发 `run-<repo>-unit`（run-once-per-SHA，防重复入队/防失败 ref 无限重试）。
- `run-<repo>-unit.yml` — 拉私有代码、跑轻量 CPU unit job、回写 status。

已接：`ext`（`ci/public-worker/unit`）、`test`（`ci/public-worker/test-unit`）、
`dynamo`（`ci/public-worker/dynamo-unit`，kvbm lifecycle 的 CPU 单测）。

## Python 参考实现（`ci_worker/`，设计说明用，不要求跑通）

`ci_worker/` 把上面那套 workflow 用 Python 重新表达一遍，作为设计参考/文档，零第三方
依赖（标准库 urllib + subprocess）。三块职责与 workflow 一一对应：

| 模块 | 对应 | 职责 |
| --- | --- | --- |
| `poller.py` | `poll-*.yml` | 扫 open PR + main，run-once-per-SHA 派发 |
| `worker.py` | `run-*-unit.yml` | insteadOf clone → 跑 unit → 回写 status |
| `github.py` | — | 最小 REST 客户端 + statuses 封装 |
| `targets.py` | — | 每个私有仓库一份 Target（repo/context/event/steps） |

入口：

```bash
export GIE_GIT_TOKEN=...
python -m ci_worker poll --target ext
python -m ci_worker run  --target ext --ref <sha-or-branch>
```

安全模型同 workflow 方案：私有代码永不提交进本仓库，token 只进 git 配置、不打印不落盘。
