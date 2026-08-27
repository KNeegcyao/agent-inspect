"""决策点序列化:契约形态(docs/contracts.md §1-2)与原始行的透明解析。

- persist 前把框架对象规整为契约 dict(input_context / output)。
- 读取时把原始行(raw row,含 context diff 引用 / blob 引用)解析回完整决策点 dict。
"""
from __future__ import annotations

import json
from typing import Any, Optional


class Serializer:
    # ---- 契约形态构建(kind 相关)----
    @staticmethod
    def llm_input(messages, model: Optional[str], params: dict) -> dict:
        return {
            "messages": [
                {"role": _role_of(m), "content": _content_of(m)} for m in _as_list(messages)
            ],
            "model": model,
            "params": params or {},
        }

    @staticmethod
    def llm_output(content, tool_calls=None) -> dict:
        return {"content": content, "tool_calls": tool_calls or []}

    @staticmethod
    def tool_input(tool_name: str, args) -> dict:
        return {"tool": tool_name, "args": args}

    @staticmethod
    def tool_output(result, is_error: bool = False) -> dict:
        return {"result": _jsonable(result), "is_error": is_error}

    # ---- 原始行 → 完整决策点 dict(回放/API/UI 消费)----
    def resolve_dp(self, store, dp, context_snap) -> dict:
        """dp 可以是 _models.DecisionPoint 或 sqlite row 已转换对象。"""
        input_context = self._resolve_input(store, context_snap, dp)
        output = self._resolve_output(store, dp)
        meta = _jsonable(dp.meta)
        return {
            "id": dp.id,
            "trace_id": dp.trace_id,
            "branch_id": dp.branch_id,
            "step_index": dp.step_index,
            "kind": dp.kind,
            "agent_id": dp.agent_id,
            "input_context": input_context,
            "output": output,
            "output_hash": dp.output_hash,
            "cause_edge": list(dp.cause_edge or []),
            "meta": meta,
        }

    def _resolve_input(self, store, context_snap, dp) -> Any:
        raw = dp.input_context
        if isinstance(raw, dict) and "context_diff_ref" in raw:
            return context_snap.reconstruct(store, dp.branch_id, dp.step_index)
        if isinstance(raw, dict) and "blob_ref" in raw:
            return self._deref(store, raw["blob_ref"])
        return raw

    def _resolve_output(self, store, dp) -> Any:
        if dp.output is None:
            return None
        if isinstance(dp.output, dict) and "blob_ref" in dp.output:
            return self._deref(store, dp.output["blob_ref"])
        return dp.output

    @staticmethod
    def _deref(store, blob_hash: str) -> Any:
        content = store.get_blob(blob_hash)
        if content is None:
            return {"blob_ref": blob_hash}
        try:
            return json.loads(content)
        except Exception:
            return content


def _role_of(m) -> str:
    if isinstance(m, dict):
        return m.get("role", "user")
    role = getattr(m, "type", None) or getattr(m, "role", None)
    return role or "user"


def _content_of(m) -> Any:
    if isinstance(m, dict):
        return m.get("content")
    return getattr(m, "content", None)


def _as_list(messages) -> list:
    if messages is None:
        return []
    if isinstance(messages, (list, tuple)):
        return list(messages)
    if isinstance(messages, dict):
        return [messages]
    return [messages]


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        try:
            return _jsonable(obj.model_dump())
        except Exception:
            pass
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
