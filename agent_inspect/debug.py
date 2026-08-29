"""Live 调试(Mode C)核心:DebugGate + DebugController。

职责边界:
- DebugController 是全局注册表(keyed by trace_id),把面板指令路由到对应 DebugGate。
- DebugGate 每 trace 一个,持断点 / 暂停 / 步进 / 待替换输入状态,决定决策点是否放行。
- 阻塞只发生在 Agent 执行侧(threading.Event.wait / asyncio.to_thread),不碰 UI 服务事件循环。
- 断点落 `breakpoints` 表(跨会话保留);暂停/步进/修改为进程内存瞬态(design.md Key Decisions)。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from ._models import Breakpoint
from ._server.store.queries import Store

# 释放动作:命令放行暂停点时的意图
_RELEASE_CONTINUE = "continue"
_RELEASE_STEP = "step"


class DebugGate:
    """单 trace 的调试状态机。线程安全(内部锁 + threading.Event)。"""

    def __init__(
        self,
        trace_id: str,
        store: Store,
        *,
        on_event=None,
        breakpoints: Optional[list[Breakpoint]] = None,
    ) -> None:
        self.trace_id = trace_id
        self._store = store
        self.on_event = on_event  # callback(event_name, payload)
        self._lock = threading.Lock()

        self.attached = False
        self.breakpoints: list[Breakpoint] = list(breakpoints or [])
        self.pause_requested = False
        self.step_mode = False  # 放行后下一个决策点即暂停(单步)
        self.pending_modify: Optional[dict] = None
        self._waiting = False
        self.paused_at: Optional[int] = None
        self.paused_payload: Optional[dict] = None
        self._release = threading.Event()
        self._release_action: Optional[str] = None

    # ------------------------------------------------------------------
    # 拦截器咨询点(决策点边界,真实执行前)
    # ------------------------------------------------------------------
    def consult(self, dp) -> Optional[dict]:
        """决定当前决策点是否放行。

        未附加(attached=False)或未命中任何暂停条件 → 直接放行(零额外语义)。
        命中 → 阻塞等待指令(step/continue/modify),返回待替换输入(若有)。
        """
        with self._lock:
            if not self.attached:
                return None
            if not self._should_pause_locked(dp):
                return None
            self._waiting = True
            self.paused_at = dp.step_index
            self.paused_payload = _paused_payload(dp)
            self._release.clear()
        if self.on_event is not None:
            self.on_event("trace.paused", dict(self.paused_payload))
        self._release.wait()  # 阻塞 Agent 执行侧;指令经其它线程 set() 放行
        with self._lock:
            self._waiting = False
            self.paused_at = None
            self.paused_payload = None
            action = self._release_action
            self._release_action = None
            if action == _RELEASE_STEP:
                self.step_mode = True
            elif action == _RELEASE_CONTINUE:
                self.step_mode = False
            mod = self._take_modify_locked(dp.step_index)
        if self.on_event is not None:
            self.on_event(
                "trace.resumed",
                {
                    "trace_id": self.trace_id,
                    "step_index": dp.step_index,
                    "action": action or _RELEASE_CONTINUE,
                },
            )
        return mod

    def _should_pause_locked(self, dp) -> bool:
        """命中判定:手动暂停 → 单步 → 断点(按 kind / agent_id / 输入子串)。"""
        if self.pause_requested:
            self.pause_requested = False
            return True
        if self.step_mode:
            self.step_mode = False
            return True
        return any(bp.enabled and _bp_matches(bp, dp) for bp in self.breakpoints)

    def _take_modify_locked(self, step: int) -> Optional[dict]:
        if self.pending_modify is not None and self.pending_modify.get("step") == step:
            mod = self.pending_modify
            self.pending_modify = None
            return mod
        self.pending_modify = None
        return None

    # ------------------------------------------------------------------
    # 面板指令
    # ------------------------------------------------------------------
    def attach(self) -> bool:
        """附加调试:之后的决策点都经此门。返回是否首次附加。"""
        with self._lock:
            if self.attached:
                return False
            self.attached = True
            return True

    def add_breakpoint(
        self,
        *,
        kind: Optional[str] = None,
        agent_id: Optional[str] = None,
        condition: Optional[str] = None,
    ) -> Breakpoint:
        bp = self._store.add_breakpoint(
            self.trace_id, kind=kind, agent_id=agent_id, condition=condition
        )
        with self._lock:
            self.breakpoints.append(bp)
        if self.on_event is not None:
            self.on_event("breakpoint.set", bp.to_dict())
        return bp

    def remove_breakpoint(self, bp_id: str) -> bool:
        with self._lock:
            before = len(self.breakpoints)
            self.breakpoints = [b for b in self.breakpoints if b.id != bp_id]
            removed = len(self.breakpoints) < before
        persisted = self._store.remove_breakpoint(self.trace_id, bp_id)
        if removed and self.on_event is not None:
            self.on_event(
                "breakpoint.removed",
                {"trace_id": self.trace_id, "breakpoint_id": bp_id},
            )
        return removed or persisted

    def pause(self) -> None:
        with self._lock:
            self.pause_requested = True

    def step(self, at_step: Optional[int] = None) -> bool:
        """单步放行。at_step 给定时仅当仍停在该暂停点才放行(重复/过期指令幂等忽略)。"""
        return self._issue_release(at_step, _RELEASE_STEP)

    def resume(self, at_step: Optional[int] = None) -> bool:
        """继续放行。at_step 语义同 step。"""
        return self._issue_release(at_step, _RELEASE_CONTINUE)

    def _issue_release(self, at_step: Optional[int], action: str) -> bool:
        """放行暂停点;返回是否真的放行。

        at_step 绑定暂停代际:指令送达时代码可能已前进(网络重试/迟到指令),
        不匹配当前暂停点则忽略,避免一次重复投递跳过一个暂停点。
        """
        with self._lock:
            if at_step is not None and self.paused_at != at_step:
                return False
            self._release_action = action
            self._release.set()
            return True

    def modify(self, step: int, field: str, value: Any, action: str = _RELEASE_CONTINUE) -> None:
        """替换待执行决策点输入并放行(action ∈ continue / step)。

        放行绑定到修改的目标 step:仅当仍停在该步骤才释放;重复投递的 modify
        不会误放已前进到的其它暂停点,其修改暂存待该步骤暂停时生效。
        """
        with self._lock:
            self.pending_modify = {"step": step, "field": field, "value": value}
            if self.paused_at == step:
                self._release_action = action
                self._release.set()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def state(self) -> dict:
        with self._lock:
            return {
                "trace_id": self.trace_id,
                "attached": self.attached,
                "paused_at": self.paused_at,
                "waiting": self._waiting,
                "breakpoints": [b.to_dict() for b in self.breakpoints],
            }


class DebugController:
    """全局调试门注册表(trace_id → DebugGate)。作用域按 trace 隔离。"""

    def __init__(self, store: Store, *, on_event=None) -> None:
        self._store = store
        self.on_event = on_event
        self._gates: dict[str, DebugGate] = {}
        self._lock = threading.Lock()

    def ensure_gate(self, trace_id: str) -> DebugGate:
        with self._lock:
            gate = self._gates.get(trace_id)
            if gate is None:
                gate = DebugGate(
                    trace_id,
                    self._store,
                    on_event=self.on_event,
                    breakpoints=self._store.list_breakpoints(trace_id),
                )
                self._gates[trace_id] = gate
            return gate

    def gate(self, trace_id: str) -> Optional[DebugGate]:
        with self._lock:
            return self._gates.get(trace_id)

    def drop_gate(self, trace_id: str) -> None:
        with self._lock:
            self._gates.pop(trace_id, None)

    def attached_trace_ids(self) -> set[str]:
        with self._lock:
            return {tid for tid, g in self._gates.items() if g.attached}

    def consult(self, trace_id: str, dp) -> Optional[dict]:
        """拦截器决策点边界入口:按 trace 路由到对应门(未附加即零开销放行)。"""
        gate = self.ensure_gate(trace_id)
        return gate.consult(dp)


def _bp_matches(bp: Breakpoint, dp) -> bool:
    if bp.kind and dp.kind != bp.kind:
        return False
    if bp.agent_id and bp.agent_id not in (dp.agent_id or ""):
        return False
    if bp.condition:
        haystack = json.dumps(dp.input_context, ensure_ascii=False, default=str)
        if bp.condition not in haystack:
            return False
    return True


def _paused_payload(dp) -> dict:
    """暂停点载荷:登记态(已含完整输入,output 待执行),供面板实时展示。"""
    return {
        "trace_id": dp.trace_id,
        "branch_id": dp.branch_id,
        "step_index": dp.step_index,
        "kind": dp.kind,
        "agent_id": dp.agent_id,
        "input_context": _jsonable(dp.input_context),
        "output": None,
    }


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
