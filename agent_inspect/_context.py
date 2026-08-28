"""执行模式上下文:通过 contextvars 在进程内贯穿 async,不引入全局可变单例。

契约见 docs/contracts.md §4。拦截器唯一读取这套上下文来决定真调/回放。
"""
from __future__ import annotations

import contextvars
import threading
from typing import Optional

MODE_RECORD = "record"
MODE_REPLAY = "replay"
MODE_FORK = "fork"


class ExecutionCursor:
    """当前执行游标(可变,经 contextvars 传播)。

    每个分支/异步任务持有独立游标。step_index 为该分支内递增的决策点序号(0-based)。
    """

    __slots__ = (
        "trace_id",
        "branch_id",
        "mode",
        "replay_branch_id",
        "replay_cursor",
        "branch_from_step",
        "dry_run",
        "sandbox",
        "live_debug",
        "last_dp_id",
        "_step_index",
        "_lock",
    )

    def __init__(
        self,
        *,
        trace_id: str,
        branch_id: str,
        mode: str = MODE_RECORD,
        replay_branch_id: Optional[str] = None,
        replay_cursor: int = 0,
        branch_from_step: int = 0,
        dry_run: bool = False,
        sandbox: Optional[dict] = None,
        live_debug: bool = False,
    ) -> None:
        self.trace_id = trace_id
        self.branch_id = branch_id
        self.mode = mode
        # replay/fork 前缀从该分支读 recorded output;record 模式为 None
        self.replay_branch_id = replay_branch_id
        self.replay_cursor = replay_cursor
        self.branch_from_step = branch_from_step
        self.dry_run = dry_run
        # Fork 副作用沙箱:按决策点 kind 配置的策略 {kind: allow|dry-run|block}
        self.sandbox = sandbox
        # Mode C:live 调试标记(决策点边界咨询调试门;record/replay/fork 之上正交)
        self.live_debug = live_debug
        self.last_dp_id: Optional[str] = None
        self._step_index = -1
        self._lock = threading.Lock()

    def next_step(self) -> int:
        """登记下一个决策点时分配 step_index。"""
        with self._lock:
            self._step_index += 1
            return self._step_index

    @property
    def step_index(self) -> int:
        return self._step_index


_cursor: contextvars.ContextVar[Optional[ExecutionCursor]] = contextvars.ContextVar(
    "agent_inspect_cursor", default=None
)


def get_cursor() -> Optional[ExecutionCursor]:
    return _cursor.get()


def set_cursor(cursor: Optional[ExecutionCursor]) -> contextvars.Token:
    return _cursor.set(cursor)


def reset_cursor(token: contextvars.Token) -> None:
    _cursor.reset(token)


def current_mode() -> str:
    cur = _cursor.get()
    return cur.mode if cur is not None else MODE_RECORD