"""ci_worker — 一个简易的通用 CI worker（调度器 + 多节点 worker）。

纯标准库实现（http.server / urllib / threading / subprocess），无第三方依赖。
三块职责：

  scheduler   调度器：HTTP 服务 + 任务队列 + worker 注册表
  worker      执行节点：动态注册、心跳、拉任务、执行、回传结果
  client      提交/查询任务的 HTTP 客户端

任务通过 HTTP 接口提交；worker 动态注册并周期心跳，调度器把队列里的任务派给
空闲 worker。与私有仓库、GitHub 均无耦合，是纯通用的「提交命令 → 分发执行 → 收集
结果」框架。
"""

__all__ = ["task", "scheduler", "worker", "client"]
