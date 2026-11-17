# ci-worker

一个简易的通用 CI worker：调度器 + 多节点 worker，任务通过 HTTP 接口提交，worker
动态注册。纯 Python 标准库实现，无第三方依赖。

## 架构

```
               提交任务 (HTTP POST /tasks)
  ┌────────┐ ────────────────────────────►  ┌───────────────┐
  │ client │                                │   scheduler   │  任务队列 + worker 注册表
  └────────┘ ◄────────────────────────────  └───────┬───────┘  (http.server 多线程)
              查询结果 (GET /tasks/<id>)             │
                                         注册/心跳/拉任务/回传结果
                                                    │
                        ┌──────────────┬────────────┼──────────────┐
                        ▼              ▼            ▼              ▼
                   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
                   │ worker  │   │ worker  │   │ worker  │   │ worker  │
                   └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

- **scheduler**（`scheduler.py`）：`http.server` 起一个 HTTP 服务，维护 FIFO 任务队列
  和 worker 注册表。任务派发用**拉取模型**——worker 空闲时来要任务，调度器不主动连
  worker，节点之间完全解耦。
- **worker**（`worker.py`）：启动时 `POST /workers/register` 注册，后台线程周期心跳
  保活；主循环空闲时 `POST /workers/<id>/next` 拉任务，`subprocess` 执行命令，回传
  成功/失败与输出。可起任意多个节点。
- **client**（`client.py`）：提交任务、查状态、列 worker 的 HTTP 客户端。

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/tasks` | 提交任务，`{"command": "..."}` |
| GET  | `/tasks` | 任务列表 |
| GET  | `/tasks/<id>` | 单个任务状态与结果 |
| POST | `/workers/register` | worker 注册，`{"name", "labels"}` |
| POST | `/workers/<id>/heartbeat` | 刷新存活 |
| GET  | `/workers` | worker 列表（含 `online`） |
| POST | `/workers/<id>/next` | 拉下一个待派任务（无则 204） |
| POST | `/tasks/<id>/result` | 回传结果，`{"status", "output"}` |

## 使用

```bash
# 1. 起调度器
python -m ci_worker scheduler --host 0.0.0.0 --port 8080

# 2. 起若干 worker 节点（可分布在不同机器，--scheduler 指向调度器）
python -m ci_worker worker --scheduler http://127.0.0.1:8080 --name node1
python -m ci_worker worker --scheduler http://127.0.0.1:8080 --name node2

# 3. 提交任务、查看结果
python -m ci_worker submit --scheduler http://127.0.0.1:8080 --command "echo hello"
python -m ci_worker tasks   --scheduler http://127.0.0.1:8080
python -m ci_worker workers --scheduler http://127.0.0.1:8080
```

任务无持久化（内存队列，重启即丢）；worker 超过 30 秒没心跳会被标记离线。这些是
刻意留的简化，作为骨架示例，不做生产级高可用。

## test 的 Nix setup（P1，main 默认尚未切换）

`run-test-unit.yml` 的 `setup=nix` 在被测提交的 `devShells.default` 内运行原入口、static 和 4 个单测分片，report 沿用原 exact-ID 汇总。Nix 模式不再执行 uv 环境安装或选择宿主 Rust。所有模式保留 `ci/public-worker/test-unit`；只有显式的 `poison_host=true` 负对照使用独立的 `ci/public-worker/test-unit-host-poison-<setup>`，避免覆盖正常门禁。

全局只用仓库变量 `TEST_UNIT_SETUP` 选择 `legacy` / `nix`，未设置时为 `legacy`；手动 dispatch 的 `setup` 可在 PR 阶段覆盖。**本 PR 不更改 main 的变量或分支保护**。审完启用：将 ci-worker 仓库变量设为 `nix`；回退：同一个变量设为 `legacy`。旧提交没有仓库入口时继续走 fallback，已有入口和检查名不变。

按 11-17 最新约定，各 runner 只复用自己的 `/nix/store`；不配置项目外部缓存、跨机 substituter、Actions store 备份或 nix-serve。产物中 `local-store-cold.seconds` 是该 runner 首次求值/实现 devShell 的墙钟（含依赖准备），`local-store-hot.seconds` 是同一 runner 再次实现的墙钟，`test-execution.seconds` 只计已实现环境内的测试；不是跨机下载计时。不同 job 位于独立 runner，各自有独立的冷/热记录。

`poison_host=true` 在入口之前移除 PATH 中所有提供 rustc 的目录，并将 python/python3 替换为退出 93 的命令；先把突变生效证据写入 `host-poison.txt`。相同突变在 legacy setup 必须失败、Nix 模式必须通过。详细验收与计时见 test 仓库 `docs/nix-toolchain.md` 和设计正本：
https://coretokenai.feishu.cn/wiki/IVk3wbr9jiCHeUk4H3Nc9VNGnYf
