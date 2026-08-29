"""Recorder:决策点序列化、增量上下文快照、大对象去重与落盘。

职责边界:不做执行模式路由(交 interceptor),只负责把决策点变成可持久化、可查询、可重建的形态。
"""
from __future__ import annotations

from typing import Optional

from .serializer import Serializer
from .dedup import Dedup
from .context_snap import ContextSnap
from .._server.store import queries as store_mod

__all__ = ["Recorder", "Serializer", "Dedup", "ContextSnap"]


class Recorder:
    """协调 serializer / dedup / context_snap,并把决策点写入 store。

    record_mode: "dev"(全量,超阈值去重)/ "prod"(摘要 + 大对象 hash 引用)。
    """

    def __init__(
        self,
        store: "store_mod.Store",
        *,
        record_mode: str = "dev",
        blob_threshold: int = 4096,
        on_event=None,
        parent_trace_id: Optional[str] = None,
    ) -> None:
        self.store = store
        self.record_mode = record_mode
        self.serializer = Serializer()
        self.dedup = Dedup(threshold=blob_threshold)
        self.context_snap = ContextSnap()
        self.on_event = on_event  # callback(event_name, payload) 供 SSE 推送
        self.parent_trace_id = parent_trace_id  # 跨进程父 trace(id),无则 None

    # ---- trace / branch ----
    def create_trace_and_root(self, agent_name: str = "agent"):
        return self.store.create_trace_with_root(agent_name, parent_trace_id=self.parent_trace_id)

    # ---- persist ----
    def persist(self, dp) -> None:
        """已完成登记的决策点立即落盘(崩溃/中止不丢已完成者)。"""
        # 增量上下文快照:dp.input_context 替换为 diff 引用
        self.context_snap.record(self.store, dp)
        # 大对象去重:output 大则存 blob;input_context 为 diff 引用(小)原样保留
        if dp.output is not None:
            dp.output = self.dedup.maybe_store(self.store, dp.output, self.record_mode)
        self.store.write_decision_point(dp)
        if self.on_event is not None:
            self.on_event(
                "decision_point", self.serializer.resolve_dp(self.store, dp, self.context_snap)
            )

    # ---- 供 interceptor / 回放读 ----
    def read_decision_point(self, trace_id: str, branch_id: str, step_index: int):
        raw = self.store.get_decision_point(trace_id, branch_id, step_index)
        if raw is None:
            return None
        return self.serializer.resolve_dp(self.store, raw, self.context_snap)

    def read_branch_points(self, trace_id: str, branch_id: str, from_step: int = 0, to_step=None):
        rows = self.store.get_decision_points(trace_id, branch_id, from_step, to_step)
        return [self.serializer.resolve_dp(self.store, r, self.context_snap) for r in rows]
