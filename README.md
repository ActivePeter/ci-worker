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

## test 的可回退环境选择

`run-test-unit.yml` 只负责控制面：`setup` dispatch 输入优先于仓库变量 `TEST_UNIT_SETUP`，未设置时为 **legacy**。目标仓 `.github/ci/public-unit.sh` 的 setup/run/report 与原生 action 使用同一个选择；legacy 实际走原 `testkit env prepare`，Nix 的安装、锁定环境、隔离和计时统一由 test 仓 `nix/ci.sh` / `scripts/ci_nix.py` 实现。worker 保持目标仓负责安装和setup；仅显式启用GHA缓存时，保存步骤额外用 `print-dev-env --profile` 冻结原环境的闭包。没有目标入口和 `nix/ci.sh` 的旧提交只支持 legacy，显式选择 nix 会拒绝。

正常门禁始终为 `ci/public-worker/test-unit`。`poison_host=true` 只污染目标入口子进程，移除提供 rustc 的 PATH 目录，将 python/python3 替换为 exit93，记录 `host-poison.txt`；负对照使用独立的 `ci/public-worker/test-unit-host-poison-<setup>`。concurrency 同时区分 PR/branch、setup 和 poison/clean。prepare 与最终状态回写使用隔离的标准库 Python；matrix/report 作业及其产物步骤任一失败、或必需 report 缺失，都不能回写成功。Dynamo/ext 保持默认 legacy 路线。

本 PR 不修改 main 的仓库变量、分支保护或必需 context，也不切换默认门禁。环境和计量的唯一集成点是 [test#187](https://github.com/goodputai/test/pull/187)，协议见[协调评论](https://github.com/goodputai/test/pull/187#issuecomment-6943572817)；本批吸收 [worker#4](https://github.com/ActivePeter/ci-worker/pull/4) 的选择、dispatch 和负控隔离。执行机仍只复用各自本机store，不部署nix-serve。公共托管CI可按#190的已批准例外使用GHA cache；legacy/nix默认切换或必需门禁变更仍须先报审。

## dag-panel 公共门禁

ActivePeter/dag-panel 使用 `poll-dag-panel.yml` 每 5 分钟轮询开放的同仓 PR、受保护分支和默认分支，
由 `run-dag-panel-unit.yml` 调用公共 `unit.yml`，最终回写 **ci/public-worker/dag-panel-unit**。
测试入口优先取被测提交的 `.github/ci/public-unit.sh`；旧提交使用 `ci/defaults/dag-panel.sh`。
入口保留 lint、Go race/coverage、smoke、regression、performance、采集与面板检查；
有 UI1 代码的提交额外运行真实浏览器分页/拖动/触摸验收并上传截图。
Go 版本读取 go.mod，Node 和 pnpm 版本由目标仓声明；不占 GPU、不部署服务。
私仓原 GitHub-hosted 任务因计费无法启动时，以此独立 context 的实际回写结果验收。

## 公共 test CI 的可选 Nix GHA 缓存

`nix_cache=on|off|auto` 控制恢复；auto读取仓库变量 `TEST_UNIT_NIX_CACHE`，未设置等同off。
本次代码合入保持变量未设置，默认行为不变。仅goodputai/test的nix路线使用该功能，
Dynamo/ext及已有store、自托管runner继续原流程。

索引按runner系统/架构、flake.lock及环境输入摘要共享；store键另含冻结manifest完整指纹。
每个分片和report只读同一份store；只有ci-worker main上的static且测试SHA已在test main历史中才保存。
源代码继续从本次测试SHA求值，旧环境回执不恢复。每次命中仍逐requisite验证内容；
污染则隔离本次恢复的空store，原setup冷装。超过8GiB不保存，由GitHub原生LRU在仓库10GiB配额内淘汰旧键。

`Nix cache contract` 为独立CI必跑项，真实两路径隔离store直接穿过生产恢复门，
覆盖传递依赖污染拒绝、隔离后冷重建、撤掉验证后漏检，以及PR/主线历史写权限。
同源设计与冷热实测证据：[NIX-GHA-CACHE-D](https://coretokenai.feishu.cn/docx/TpXLdFgKVoYPEsx5VvTc33G7n4g)。

保存时记录bootstrap的canonical store/bin/nix路径及二进制SHA256；恢复时核对路径、hash
和同目录nix-store可执行性，因此HOME下XDG用户profile未被缓存也能运行。v2缓存键隔离早期profile恢复未命中的试跑。
