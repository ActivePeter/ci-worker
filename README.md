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
