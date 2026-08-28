"""Fork 引擎:反事实分支的发起、前缀回放边界与注入修改。

职责边界:
- 创建 fork 分支(parent_branch_id + branch_from_step),入待执行队列。
- 持有按分支的注入修改表(改 prompt / 工具返回 / 参数)。
- 拦截器经 `consume_pending_fork()` 消费一个待执行 fork,并按 `modification_for()`
  在对应 step 注入修改(design.md「前缀确定性回放 + 注入 + 后缀真调」)。
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from ._server.store.queries import Store
from . import _models as m

BIG_STEP = 2**31


class ForkError(Exception):
    """Fork 发起校验失败(空链 / 越界起点)。"""


@dataclass
class ForkPlan:
    trace_id: str
    branch_id: str
    origin_branch: str
    branch_from_step: int
    dry_run: bool = False


@dataclass
class Modification:
    """对分支起点决策点的注入:field ∈ {"output", "input_context.<path>"}。"""

    step: int
    field: str
    value: Any

    def to_dict(self) -> dict:
        return {"step": self.step, "field": self.field, "value": self.value}


class ForkController:
    """全局唯一 fork 调度器:待执行队列 + 按分支注入修改表。线程安全。"""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._pending: deque[ForkPlan] = deque()
        self._mods: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    # ---- 发起 ----
    def request_fork(
        self,
        *,
        trace_id: str,
        from_branch: str,
        from_step: int,
        modifications: Optional[list[Modification]] = None,
        dry_run: bool = False,
        note: Optional[str] = None,
    ) -> tuple[m.Branch, ForkPlan]:
        """从已记录决策点发起新分支。前缀 0..from_step-1 回放,后缀 from_step 起真调。

        校验:
        - 空链(该 trace 无任何决策点)拒绝 → spec `fork.空链 Fork`
        - from_step 越界拒绝,避免产生无起点的分支
        - from_branch 归属校验:父分支必须存在且属于 trace_id,避免跨 trace 错位
          (采纳跨 trace 值 → 新分支仍创建于主分支所在 trace) → spec `adopt-cross-trace.采纳分支归属校验`
        """
        if self._store.count_decision_points(trace_id) == 0:
            raise ForkError(
                f"cannot fork empty trace {trace_id}: no decision points recorded yet"
            )
        parent = self._store.get_branch(from_branch)
        if parent is None:
            raise ForkError(f"cannot fork: branch {from_branch} not found")
        if parent.trace_id != trace_id:
            raise ForkError(
                f"cannot fork: branch {from_branch} belongs to trace {parent.trace_id}, "
                f"not target trace {trace_id}"
            )
        last = self._store.last_step_before(from_branch, BIG_STEP) or 0
        if from_step < 0 or from_step > last + 1:
            raise ForkError(
                f"fork step {from_step} out of range for branch {from_branch} (0..{last + 1})"
            )
        branch = self._store.create_branch(
            trace_id,
            parent_branch_id=from_branch,
            branch_from_step=from_step,
            origin=m.ORIGIN_FORK,
            note=note,
        )
        self._mods[branch.id] = [x.to_dict() for x in (modifications or [])]
        plan = ForkPlan(
            trace_id=trace_id,
            branch_id=branch.id,
            origin_branch=from_branch,
            branch_from_step=from_step,
            dry_run=dry_run,
        )
        with self._lock:
            self._pending.append(plan)
        return branch, plan

    # ---- 拦截器消费 ----
    def consume_pending_fork(self) -> Optional[ForkPlan]:
        with self._lock:
            return self._pending.popleft() if self._pending else None

    def modification_for(self, branch_id: str, step: int) -> Optional[dict]:
        for mod in self._mods.get(branch_id, []):
            if mod.get("step") == step:
                return mod
        return None

    def recorded_point(self, store, recorder, trace_id: str, branch_id: str, step: int) -> Optional[dict]:
        """沿分支父链向上找已记录的决策点(嵌套 Fork 前缀复用父分支记录)。

        前缀共享(spec:不向 fork 分支复制历史),故当前分支缺步时沿 parent_branch_id 回溯。
        """
        seen: set[str] = set()
        while branch_id and branch_id not in seen:
            seen.add(branch_id)
            dp = recorder.read_decision_point(trace_id, branch_id, step)
            if dp is not None and dp.get("output") is not None:
                return dp
            branch = store.get_branch(branch_id)
            branch_id = branch.parent_branch_id if branch is not None else None
        return None

    # ---- 查询 ----
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def drop_mods(self, branch_id: str) -> None:
        with self._lock:
            self._mods.pop(branch_id, None)
