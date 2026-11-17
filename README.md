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

## testkit 的锁定 Nix 环境

`run-test-unit` 为 reusable `unit.yml` 显式选择 `runtime: nix`；Dynamo/ext 保持默认 legacy 环境。prepare 仅用标准库规划，测试 setup/run、跨 job exact-ID report 和正常的最终状态回写都使用被测 SHA 的 Nix devShell。缺锁或环境失败会判红；report 缺失不能被当作成功。

使用 cachix/install-nix-action 安装 Nix 2.35.6，只复用当前机器 `/nix/store`，正常获取锁定的官方公开依赖；不配置自建 substituter，不上传 store，也不恢复跨 runner 缓存。setup 不再安装旧镜像 Python 环境，改为验证解释器来源与 Python 锁。

每个 job 的 artifacts 保存 `nix-timings.json`、原始 Nix activity 日志和 setup/run/report 墙钟。首次 realization 与同一 job 中的立即重复 realization 分开记录；不同 hosted jobs/runs 不称热缓存。substitution、derivation build 和 file transfer 按各类别区间并集计时，类别可以重叠，不能相加；固定输出下载仍可能归入 Nix derivation build。full workflow 墙钟另与旧约 194 秒基线比较。
