"""流式决策点路由:透传 + 旁路累积,流耗尽时按累积结果登记。

与 base.py 的三态路由同语义(record/replay/fork、Live 咨询、注入、dry_run、沙箱),
差异只在"native 是流":真调返回透传累积包装(_TeeStream/_AsyncTeeStream),
回放/注入命中返回合成流(_SyntheticStream,delta 路径兼容)。
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any, Callable, Optional

from .._context import MODE_FORK, MODE_REPLAY
from .._models import DecisionPoint, new_id

# ---------------------------------------------------------------------------
# 累积与 shape
# ---------------------------------------------------------------------------
class _StreamAcc:
    """流 chunk 累积器:content 拼接、tool_calls 按 index 聚合、usage 取最后非空。"""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.tool_calls: dict[int, dict] = {}
        self.id: Optional[str] = None
        self.model: Optional[str] = None
        self.usage: Any = None

    def absorb(self, chunk: Any) -> None:
        self.id = self.id or getattr(chunk, "id", None)
        self.model = self.model or getattr(chunk, "model", None)
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self.usage = usage
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if content:
                self.parts.append(content)
            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0) or 0
                slot = self.tool_calls.setdefault(idx, {"id": None, "name": None, "args": []})
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    args = getattr(fn, "arguments", None)
                    if args:
                        slot["args"].append(args)
                if getattr(tc, "id", None):
                    slot["id"] = tc.id

    def to_acc(self) -> dict[str, Any]:
        tool_calls = []
        for idx in sorted(self.tool_calls):
            slot = self.tool_calls[idx]
            args = "".join(slot["args"])
            parsed: Any = None
            if args:
                try:
                    parsed = json.loads(args)
                except Exception:  # noqa: BLE001 - 非法 JSON 保留原文本
                    parsed = args
            tool_calls.append({"id": slot["id"], "name": slot["name"], "args": parsed})
        out: dict[str, Any] = {
            "content": "".join(self.parts),
            "tool_calls": tool_calls,
            "id": self.id,
            "model": self.model,
        }
        if self.usage is not None:
            out["usage"] = self.usage
        return out


def shape_stream(acc: dict[str, Any]) -> dict[str, Any]:
    """流累积结果 → 契约输出(与 _shape_response 同形,reconstruct 可直接回放)。"""
    out: dict[str, Any] = {
        "content": acc.get("content"),
        "tool_calls": acc.get("tool_calls", []),
    }
    for k in ("id", "model", "usage"):
        if acc.get(k):
            out[k] = acc[k]
    return out


# ---------------------------------------------------------------------------
# 流包装
# ---------------------------------------------------------------------------
class _TeeStream:
    """透传真实流并旁路累积;耗尽/关闭时按累积结果登记决策点。"""

    def __init__(self, inner: Any, on_done: Callable[[dict], None]) -> None:
        self._inner = inner
        self._it = iter(inner)
        self._acc = _StreamAcc()
        self._on_done = on_done
        self._finished = False

    def __iter__(self) -> "_TeeStream":
        return self

    def __next__(self) -> Any:
        try:
            chunk = next(self._it)
        except StopIteration:
            self._finish()
            raise
        except BaseException:
            self._finish()
            raise
        self._acc.absorb(chunk)
        return chunk

    def close(self) -> None:
        self._finish()
        inner_close = getattr(self._inner, "close", None)
        if inner_close:
            inner_close()

    def _finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._on_done(self._acc.to_acc())


class _AsyncTeeStream:
    """异步透传累积(async for);语义与 _TeeStream 一致。"""

    def __init__(self, inner: Any, on_done: Callable[[dict], None]) -> None:
        self._inner = inner
        self._acc = _StreamAcc()
        self._on_done = on_done
        self._finished = False

    def __aiter__(self) -> "_AsyncTeeStream":
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._inner.__anext__()
        except StopAsyncIteration:
            await self._finish()
            raise
        except BaseException:
            await self._finish()
            raise
        self._acc.absorb(chunk)
        return chunk

    async def aclose(self) -> None:
        await self._finish()
        inner_close = getattr(self._inner, "aclose", None) or getattr(self._inner, "close", None)
        if inner_close is not None:
            result = inner_close()
            if hasattr(result, "__await__"):
                await result

    async def _finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._on_done(self._acc.to_acc())


class _SyntheticStream:
    """回放/注入命中的合成流:单块 delta(兼容 chunk.choices[0].delta.content)。"""

    def __init__(self, output: Optional[dict]) -> None:
        self._output = output
        self._done = False

    def __iter__(self) -> "_SyntheticStream":
        return self

    def __next__(self) -> Any:
        if self._done:
            raise StopIteration
        self._done = True
        return self._one_chunk()

    def close(self) -> None:
        self._done = True

    def _one_chunk(self) -> Any:
        out = self._output or {}
        def get(key: str) -> Any:
            if isinstance(out, dict):
                return out.get(key)
            return getattr(out, key, None)

        delta = SimpleNamespace(
            content=get("content"),
            tool_calls=get("tool_calls") or None,
        )
        choice = SimpleNamespace(delta=delta, finish_reason="stop", index=0)
        return SimpleNamespace(
            id=get("id"),
            model=get("model"),
            choices=[choice],
            usage=None,
        )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
def _build_dp(interceptor, cursor, step: int, kind: str, agent_id: str, input_context: dict) -> DecisionPoint:
    dp = DecisionPoint(
        id=new_id("dp"),
        trace_id=cursor.trace_id,
        branch_id=cursor.branch_id,
        step_index=step,
        kind=kind,
        agent_id=agent_id,
        input_context=input_context,
    )
    if cursor.last_dp_id:
        dp.cause_edge = [cursor.last_dp_id]
    return dp


def _consult(interceptor, cursor, dp) -> Callable[[], Any] | None:
    """Live 咨询;命中 → 应用替换输入并返回替换后的 start_call 工厂(或 None)。"""
    if not (cursor.live_debug and interceptor.debug is not None):
        return None
    mod = interceptor.debug.consult(cursor.trace_id, dp)
    if mod is None:
        return None
    interceptor._apply_input_mod(dp, mod)
    return None  # 替换 start_call 由调用方以 make_modified_call 处理


def route_stream(
    interceptor,
    *,
    kind: str,
    agent_id: str,
    input_context: dict,
    start_call: Callable[[], Any],
    reconstruct: Callable[[Optional[dict]], Any],
    make_modified_call: Optional[Callable[[dict], Callable[[], Any]]] = None,
):
    """同步流式路由:返回流对象(真调透传累积 / 回放合成)。"""
    cursor = interceptor._ensure_cursor()
    step = cursor.next_step()
    dp = _build_dp(interceptor, cursor, step, kind, agent_id, input_context)
    if cursor.live_debug and interceptor.debug is not None:
        mod = interceptor.debug.consult(cursor.trace_id, dp)
        if mod is not None:
            interceptor._apply_input_mod(dp, mod)
            if make_modified_call is not None:
                start_call = make_modified_call(dp.input_context)
    mode = cursor.mode
    if mode == MODE_REPLAY or (mode == MODE_FORK and step < cursor.branch_from_step):
        rec = interceptor._recorded(cursor, step, lambda d: d)  # 原始契约 dict 供合成流
        if rec.found:
            return _SyntheticStream(rec.output)  # 回放命中:合成流,零真调
        return _TeeStream(start_call(), _finisher(interceptor, cursor, dp, time.perf_counter()))
    if mode == MODE_FORK:
        mod = interceptor._mod_for(cursor, step)
        if mod is not None and mod["field"] == "output":
            shaped = shape_stream({"content": mod["value"], "tool_calls": [], "id": None, "model": None})
            interceptor._finalize(dp, shaped, True, time.perf_counter(), lambda v: v, None)
            cursor.last_dp_id = dp.id
            return _SyntheticStream(shaped)
        if mod is not None and mod["field"].startswith("input_context"):
            interceptor._apply_input_mod(dp, mod)
            if make_modified_call is not None:
                start_call = make_modified_call(dp.input_context)
        if cursor.dry_run:
            interceptor._finalize(dp, None, True, time.perf_counter(), lambda v: None, None)
            cursor.last_dp_id = dp.id
            return _SyntheticStream(None)
        policy = interceptor._sandbox_policy(cursor, dp)
        if policy is not None:
            dp.meta["sandbox"] = policy
            interceptor._finalize(dp, None, True, time.perf_counter(), lambda v: None, None)
            cursor.last_dp_id = dp.id
            return _SyntheticStream(None)
    return _TeeStream(start_call(), _finisher(interceptor, cursor, dp, time.perf_counter()))


async def aroute_stream(
    interceptor,
    *,
    kind: str,
    agent_id: str,
    input_context: dict,
    start_call: Callable[[], Any],
    reconstruct: Callable[[Optional[dict]], Any],
    make_modified_call: Optional[Callable[[dict], Callable[[], Any]]] = None,
):
    """异步流式路由(await start_call / await 透传)。"""
    cursor = interceptor._ensure_cursor()
    step = cursor.next_step()
    dp = _build_dp(interceptor, cursor, step, kind, agent_id, input_context)
    if cursor.live_debug and interceptor.debug is not None:
        mod = await asyncio.to_thread(interceptor.debug.consult, cursor.trace_id, dp)
        if mod is not None:
            interceptor._apply_input_mod(dp, mod)
            if make_modified_call is not None:
                start_call = make_modified_call(dp.input_context)
    mode = cursor.mode
    if mode == MODE_REPLAY or (mode == MODE_FORK and step < cursor.branch_from_step):
        rec = interceptor._recorded(cursor, step, lambda d: d)  # 原始契约 dict 供合成流
        if rec.found:
            return _SyntheticStream(rec.output)
        stream = await start_call()
        return _AsyncTeeStream(stream, _finisher(interceptor, cursor, dp, time.perf_counter()))
    if mode == MODE_FORK:
        mod = interceptor._mod_for(cursor, step)
        if mod is not None and mod["field"] == "output":
            shaped = shape_stream({"content": mod["value"], "tool_calls": [], "id": None, "model": None})
            interceptor._finalize(dp, shaped, True, time.perf_counter(), lambda v: v, None)
            cursor.last_dp_id = dp.id
            return _SyntheticStream(shaped)
        if mod is not None and mod["field"].startswith("input_context"):
            interceptor._apply_input_mod(dp, mod)
            if make_modified_call is not None:
                start_call = make_modified_call(dp.input_context)
        if cursor.dry_run:
            interceptor._finalize(dp, None, True, time.perf_counter(), lambda v: None, None)
            cursor.last_dp_id = dp.id
            return _SyntheticStream(None)
        policy = interceptor._sandbox_policy(cursor, dp)
        if policy is not None:
            dp.meta["sandbox"] = policy
            interceptor._finalize(dp, None, True, time.perf_counter(), lambda v: None, None)
            cursor.last_dp_id = dp.id
            return _SyntheticStream(None)
    stream = await start_call()
    return _AsyncTeeStream(stream, _finisher(interceptor, cursor, dp, time.perf_counter()))


def _finisher(interceptor, cursor, dp, start: float) -> Callable[[dict], None]:
    """流耗尽回调:按累积结果 shape 并登记落盘(已完成者不丢)。"""

    def finish(acc: dict) -> None:
        shaped = shape_stream(acc)
        interceptor._finalize(dp, shaped, True, start, lambda v: v, None)
        cursor.last_dp_id = dp.id

    return finish
