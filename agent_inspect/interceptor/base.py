"""Interceptor 核心:把 LLM/工具调用包装为决策点路由点,按执行模式上下文决定真调/回放。

三种模式(record/replay/fork)共享同一段路由逻辑,只是上下文不同(design.md「三态统一」)。
拦截器不碰存储细节(交 recorder),也不渲染(交 server/ui)。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .. import _models as m
from .._context import MODE_RECORD, MODE_REPLAY, MODE_FORK, ExecutionCursor, get_cursor, set_cursor
from ..recorder import Recorder


class _Rec:
    __slots__ = ("found", "output")

    def __init__(self, found: bool, output: Any = None):
        self.found = found
        self.output = output


class Interceptor:
    """执行模式路由 + 决策点登记与落盘。sroute(同步)/ aroute(异步)。"""

    def __init__(self, recorder: Recorder, controller=None, debug=None) -> None:
        self.recorder = recorder
        self.controller = controller
        self.debug = debug  # DebugController(Mode C live 调试);None 则零行为变化

    # ------------------------------------------------------------------
    # 执行上下文
    # ------------------------------------------------------------------
    def acquire_context(self) -> tuple[ExecutionCursor, str, str]:
        """无活跃上下文时:优先消费 pending fork,否则新建 record trace。

        返回 (cursor, trace_id, branch_id)。调用方负责 set_cursor / reset_cursor。
        """
        plan = None
        if self.controller is not None:
            plan = self.controller.consume_pending_fork()
        if plan is not None:
            cursor = ExecutionCursor(
                trace_id=plan.trace_id,
                branch_id=plan.branch_id,
                mode=MODE_FORK,
                replay_branch_id=plan.origin_branch,
                branch_from_step=plan.branch_from_step,
                dry_run=plan.dry_run,
            )
            cursor.last_dp_id = self._prefix_last_dp(plan.trace_id, plan.origin_branch, plan.branch_from_step)
            self._mark_live(cursor)
            return cursor, plan.trace_id, plan.branch_id
        trace, branch = self.recorder.create_trace_and_root("agent")
        cursor = ExecutionCursor(trace_id=trace.id, branch_id=branch.id, mode=MODE_RECORD)
        self._mark_live(cursor)
        return cursor, trace.id, branch.id

    def _mark_live(self, cursor: ExecutionCursor) -> None:
        """live 调试控制器存在时:注册该 trace 的调试门并打标(Mode C 正交于 A/B)。"""
        if self.debug is None:
            return
        cursor.live_debug = True
        self.debug.ensure_gate(cursor.trace_id)

    def _prefix_last_dp(self, trace_id: str, branch_id: str, branch_from_step: int) -> Optional[str]:
        points = self.recorder.read_branch_points(trace_id, branch_id, 0, branch_from_step - 1)
        return points[-1]["id"] if points else None

    def _ensure_cursor(self):
        cursor = get_cursor()
        if cursor is None:
            cursor, _t, _b = self.acquire_context()
            set_cursor(cursor)
        return cursor

    # ------------------------------------------------------------------
    # 同步路由
    # ------------------------------------------------------------------
    def sroute(
        self,
        *,
        kind: str,
        agent_id: str,
        input_context: dict,
        call: Callable[[], Any],
        reconstruct: Callable[[dict], Any],
        shape_output: Callable[[Any], dict],
        meta_fn: Optional[Callable[[Any], dict]] = None,
        make_modified_call: Optional[Callable[[dict], Callable]] = None,
    ) -> Any:
        cursor = self._ensure_cursor()
        step = cursor.next_step()
        dp = m.DecisionPoint(
            id=m.new_id("dp"),
            trace_id=cursor.trace_id,
            branch_id=cursor.branch_id,
            step_index=step,
            kind=kind,
            agent_id=agent_id,
            input_context=input_context,
        )
        if cursor.last_dp_id:
            dp.cause_edge = [cursor.last_dp_id]
        # ---- Mode C live 调试:决策点边界咨询调试门(阻塞放行 / 替换输入)----
        if cursor.live_debug and self.debug is not None:
            mod = self.debug.consult(cursor.trace_id, dp)
            if mod is not None:
                self._apply_input_mod(dp, mod)
                if make_modified_call is not None:
                    call = make_modified_call(dp.input_context)
        start = time.perf_counter()
        err: Optional[BaseException] = None
        native: Any = None
        needs_record = True
        try:
            native, needs_record = self._decide(cursor, step, dp, call, make_modified_call, reconstruct)
        except BaseException as e:  # noqa: BLE001 - 记录后按原样抛给调用方
            err = e
            native = None
            needs_record = True
            dp.meta["error"] = {"code": type(e).__name__, "message": str(e)}
        self._finalize(dp, native, needs_record, start, shape_output, meta_fn)
        if needs_record:
            cursor.last_dp_id = dp.id
        if err is not None:
            raise err
        return native

    # ------------------------------------------------------------------
    # 异步路由
    # ------------------------------------------------------------------
    async def aroute(
        self,
        *,
        kind: str,
        agent_id: str,
        input_context: dict,
        call: Callable[[], Any],
        reconstruct: Callable[[dict], Any],
        shape_output: Callable[[Any], dict],
        meta_fn: Optional[Callable[[Any], dict]] = None,
        make_modified_call: Optional[Callable[[dict], Callable]] = None,
    ) -> Any:
        cursor = self._ensure_cursor()
        step = cursor.next_step()
        dp = m.DecisionPoint(
            id=m.new_id("dp"),
            trace_id=cursor.trace_id,
            branch_id=cursor.branch_id,
            step_index=step,
            kind=kind,
            agent_id=agent_id,
            input_context=input_context,
        )
        if cursor.last_dp_id:
            dp.cause_edge = [cursor.last_dp_id]
        # ---- Mode C live 调试:决策点边界咨询调试门(异步阻塞不卡事件循环)----
        if cursor.live_debug and self.debug is not None:
            mod = await asyncio.to_thread(self.debug.consult, cursor.trace_id, dp)
            if mod is not None:
                self._apply_input_mod(dp, mod)
                if make_modified_call is not None:
                    call = make_modified_call(dp.input_context)
        start = time.perf_counter()
        err: Optional[BaseException] = None
        native: Any = None
        needs_record = True
        try:
            native, needs_record = await self._adecide(cursor, step, dp, call, make_modified_call, reconstruct)
        except BaseException as e:  # noqa: BLE001
            err = e
            native = None
            needs_record = True
            dp.meta["error"] = {"code": type(e).__name__, "message": str(e)}
        self._finalize(dp, native, needs_record, start, shape_output, meta_fn)
        if needs_record:
            cursor.last_dp_id = dp.id
        if err is not None:
            raise err
        return native

    # ------------------------------------------------------------------
    # 模式路由(三态共享)
    # ------------------------------------------------------------------
    def _decide(self, cursor, step, dp, call, make_modified_call, reconstruct):
        mode = cursor.mode
        if mode == MODE_REPLAY:
            rec = self._recorded(cursor, step, reconstruct)
            if rec.found:
                return rec.output, False
            return call(), True  # Replay 缺记录输出时退回真调
        if mode == MODE_FORK:
            if step < cursor.branch_from_step:
                rec = self._recorded(cursor, step, reconstruct)
                if rec.found:
                    return rec.output, False
                return call(), True
            mod = self._mod_for(cursor, step)
            if mod is not None and mod["field"] == "output":
                return mod["value"], True  # 注入工具返回:不真调
            if mod is not None and mod["field"].startswith("input_context"):
                self._apply_input_mod(dp, mod)
                if make_modified_call is not None:
                    call = make_modified_call(dp.input_context)
            if cursor.dry_run:
                return reconstruct(None), True  # 只读预览:不真调
            return call(), True
        # record
        return call(), True

    async def _adecide(self, cursor, step, dp, call, make_modified_call, reconstruct):
        mode = cursor.mode
        if mode == MODE_REPLAY:
            rec = self._recorded(cursor, step, reconstruct)
            if rec.found:
                return rec.output, False
            out = call()
            return (await out) if _is_awaitable(out) else out, True
        if mode == MODE_FORK:
            if step < cursor.branch_from_step:
                rec = self._recorded(cursor, step, reconstruct)
                if rec.found:
                    return rec.output, False
                out = call()
                return (await out) if _is_awaitable(out) else out, True
            mod = self._mod_for(cursor, step)
            if mod is not None and mod["field"] == "output":
                return mod["value"], True
            if mod is not None and mod["field"].startswith("input_context"):
                self._apply_input_mod(dp, mod)
                if make_modified_call is not None:
                    call = make_modified_call(dp.input_context)
            if cursor.dry_run:
                return reconstruct(None), True
            out = call()
            return (await out) if _is_awaitable(out) else out, True
        out = call()
        return (await out) if _is_awaitable(out) else out, True

    def _recorded(self, cursor, step, reconstruct) -> _Rec:
        read_branch = cursor.replay_branch_id or cursor.branch_id
        if self.controller is not None:
            rec = self.controller.recorded_point(
                self.recorder.store, self.recorder, cursor.trace_id, read_branch, step
            )
        else:
            rec = self.recorder.read_decision_point(cursor.trace_id, read_branch, step)
        if rec is None or rec.get("output") is None:
            return _Rec(False)
        return _Rec(True, reconstruct(rec["output"]))

    def _mod_for(self, cursor, step):
        if self.controller is None:
            return None
        return self.controller.modification_for(cursor.branch_id, step)

    @staticmethod
    def _apply_input_mod(dp, mod) -> None:
        field = mod["field"]
        if field.startswith("input_context."):
            path = field[len("input_context."):].split(".")
        else:
            path = field.split(".")
        _set_path(dp.input_context, path, mod["value"])

    # ------------------------------------------------------------------
    # 收尾:填 output/meta + 落盘
    # ------------------------------------------------------------------
    def _finalize(self, dp, native, needs_record, start, shape_output, meta_fn) -> None:
        if native is not None:
            try:
                dp.output = shape_output(native)
            except Exception:  # noqa: BLE001 - 形状规整失败不阻断
                dp.output = {"raw": _jsonable(native)}
            dp.output_hash = _hash_of(dp.output)
        dp.meta["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        dp.meta["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if meta_fn is not None and native is not None:
            try:
                dp.meta.update(meta_fn(native) or {})
            except Exception:  # noqa: BLE001
                pass
        if needs_record:
            self.recorder.persist(dp)


def _set_path(obj: dict, path: list, value: Any) -> None:
    """沿路径写入值。支持 dict 键与 list 索引混合(如 `messages[0].content`)。

    中间节点按"下一段键是否为整数"决定该建 list 还是 dict;已有容器原样保留
    (不因下一段是 dict 键而覆盖既有 list,反之亦然)。
    """
    keys = []
    for p in path:
        keys.extend(_split_key(p))
    target: Any = obj
    for i, p in enumerate(keys[:-1]):
        nxt_is_int = isinstance(keys[i + 1], int)
        if isinstance(p, int):
            while len(target) <= p:
                target.append(None)
            nxt = target[p]
            if nxt is None or not isinstance(nxt, (dict, list)):
                nxt = [] if nxt_is_int else {}
                target[p] = nxt
            target = nxt
        else:
            nxt = target.get(p)
            if not isinstance(nxt, (dict, list)):
                nxt = [] if nxt_is_int else {}
                target[p] = nxt
            target = nxt
    k = keys[-1]
    if isinstance(k, int):
        while len(target) <= k:
            target.append(None)
        target[k] = value
    else:
        target[k] = value


_BRACKET = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]")


def _split_key(key: str) -> list:
    """把 `messages[0]` 拆成 ["messages", 0];无括号时原样返回 [key]。"""
    parts: list = []
    pos = 0
    for mo in _BRACKET.finditer(key):
        if mo.start() > pos:
            parts.append(key[pos : mo.start()])
        parts.append(mo.group(1))
        parts.append(int(mo.group(2)))
        pos = mo.end()
    if pos < len(key):
        parts.append(key[pos:])
    return parts or [key]


def _hash_of(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _is_awaitable(x: Any) -> bool:
    return hasattr(x, "__await__")
