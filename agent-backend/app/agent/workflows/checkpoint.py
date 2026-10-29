"""工作流编排层：LangGraph checkpoint 共享实例。

「出题后暂停、作答后恢复」的执行现场存放在 checkpoint 中，
workflow_runs.state_json 只保留业务快照；两者用同一个 run_id 关联。
MemorySaver 是进程内存储：服务重启 / 多进程部署后旧线程无法恢复，
这是当前方案已知的限制，由业务层在恢复前显式校验。
"""

import threading

from langgraph.checkpoint.memory import MemorySaver

__all__ = ["build_thread_config", "get_workflow_checkpointer"]

_checkpointer: MemorySaver | None = None
_lock = threading.Lock()


def get_workflow_checkpointer() -> MemorySaver:
    """双检锁单例：所有图共用一份 checkpoint，避免各自持有独立的线程表。"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    with _lock:
        if _checkpointer is None:
            _checkpointer = MemorySaver()
    return _checkpointer


def build_thread_config(thread_id: str) -> dict:
    """thread_id 即 workflow_runs.run_id：同一 run 的启动与恢复共用一个线程。"""
    return {"configurable": {"thread_id": thread_id}}
