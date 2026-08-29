"""外部 span 导出导入:把遵循 OpenInference 语义约定的 span 树映射为决策点 trace。

只读映射,不碰拦截器与记录路径;落库复用 recorder.persist(增量快照 + 大对象去重),
导入产物与自录 trace 同构——查看 / Fork / 分支 diff 零改动复用。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from . import _models as m
from ._server.store.queries import Store
from .interceptor.base import _hash_of
from .recorder import Recorder

KIND_ATTR = "openinference.span.kind"
SPAN_KIND_LLM = "LLM"
SPAN_KIND_TOOL = "TOOL"


class TraceImportError(Exception):
    """导入校验失败(非 JSON 对象 / 缺 span 树 / 无可映射 span)。不产生任何写入。"""


@dataclass
class ImportResult:
    trace_id: str
    root_branch_id: str
    decision_points: int
    skipped: int


def import_trace(store: Store, recorder: Recorder, payload: Any) -> ImportResult:
    """导入一份 span 导出 JSON,返回导入统计。失败抛 TraceImportError,不落库。

    接受两种形态:OTLP JSON 信封(resourceSpans[].scopeSpans[].spans[])或
    扁平 span 列表({"spans": [...]},属性为 {key: value} 对象)。
    """
    spans, agent_name = _extract_spans(payload)
    ordered = _order_spans(spans)
    mapped = [s for s in ordered if _span_kind(s) in (SPAN_KIND_LLM, SPAN_KIND_TOOL)]
    skipped = len(ordered) - len(mapped)
    if not mapped:
        raise TraceImportError(
            "no importable spans found: need spans with "
            f"{KIND_ATTR} in ({SPAN_KIND_LLM}, {SPAN_KIND_TOOL})"
        )

    starts = [_start_sec(s) for s in ordered if _start_sec(s) > 0]
    started_at = min(starts) if starts else m.now()

    trace, branch = store.create_trace_with_root(agent_name, parent_trace_id=None)
    prev_dp_id: Optional[str] = None
    count = 0
    for span in mapped:
        dp = _dp_from_span(trace.id, branch.id, count, span, prev_dp_id)
        if dp.output is not None:
            dp.output_hash = _hash_of(dp.output)
        recorder.persist(dp)
        prev_dp_id = dp.id
        count += 1

    store.set_trace_lifecycle(trace.id, m.LIFECYCLE_DONE)
    store.set_trace_started_at(trace.id, started_at)
    return ImportResult(
        trace_id=trace.id, root_branch_id=branch.id, decision_points=count, skipped=skipped
    )


# ---------------------------------------------------------------------------
# 输入形态:OTLP 信封 / 扁平列表
# ---------------------------------------------------------------------------
def _extract_spans(payload: Any) -> tuple[list[dict], str]:
    if not isinstance(payload, dict):
        raise TraceImportError("export must be a JSON object")
    agent_name = "imported"
    spans: list[dict] = []
    resource_spans = payload.get("resourceSpans")
    if isinstance(resource_spans, list):
        for res in resource_spans:
            if not isinstance(res, dict):
                continue
            name = _resource_service_name(res)
            if name:
                agent_name = name
            for scope in res.get("scopeSpans") or []:
                if isinstance(scope, dict):
                    spans.extend(s for s in scope.get("spans") or [] if isinstance(s, dict))
    elif isinstance(payload.get("spans"), list):
        spans = [s for s in payload["spans"] if isinstance(s, dict)]
        agent_name = payload.get("agent_name") or payload.get("service.name") or agent_name
    if not spans:
        raise TraceImportError(
            "no spans found in export (need resourceSpans[].scopeSpans[].spans[] or spans[])"
        )
    return spans, str(agent_name)


def _resource_service_name(res: dict) -> Optional[str]:
    attrs = res.get("resource", {}).get("attributes")
    flat = _flatten_otlp_attrs(attrs) if isinstance(attrs, list) else (attrs or {})
    name = flat.get("service.name")
    return str(name) if name else None


# ---------------------------------------------------------------------------
# span 字段读取(OTLP camelCase / 扁平 snake_case 兼容)
# ---------------------------------------------------------------------------
def _attr_map(span: dict) -> dict:
    attrs = span.get("attributes")
    if isinstance(attrs, list):
        return _flatten_otlp_attrs(attrs)
    if isinstance(attrs, dict):
        return attrs
    return {}


def _flatten_otlp_attrs(attrs: list) -> dict:
    """OTel 属性数组 [{key, value:{stringValue|...}}] → {key: python_value}。"""
    out: dict = {}
    for a in attrs or []:
        if not isinstance(a, dict) or not a.get("key"):
            continue
        out[a["key"]] = _otlp_value(a.get("value"))
    return out


def _otlp_value(v: Any) -> Any:
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            return v[k]
    if "arrayValue" in v and isinstance(v["arrayValue"], dict):
        return [_otlp_value(x) for x in v["arrayValue"].get("values") or []]
    if "kvlistValue" in v and isinstance(v["kvlistValue"], dict):
        return _flatten_otlp_attrs(v["kvlistValue"].get("values") or [])
    return v


def _span_id(span: dict) -> str:
    sid = span.get("spanId") or span.get("span_id") or ""
    return str(sid)


def _parent_id(span: dict) -> str:
    pid = span.get("parentSpanId") or span.get("parent_span_id") or ""
    return str(pid)


def _raw_start(span: dict) -> float:
    v = span.get("startTimeUnixNano")
    if v is None:
        v = span.get("start_time")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _start_sec(span: dict) -> float:
    """起始时间归一到秒(自动识别 ns / µs / ms / s 数量级)。"""
    n = _raw_start(span)
    return n / _unit_divisor(n)


def _unit_divisor(n: float) -> float:
    if n >= 1e17:
        return 1e9  # ns
    if n >= 1e14:
        return 1e6  # µs
    if n >= 1e11:
        return 1e3  # ms
    return 1.0  # s


def _duration_ms(span: dict) -> Optional[float]:
    e = span.get("endTimeUnixNano")
    if e is None:
        e = span.get("end_time")
    try:
        end = float(e)
    except (TypeError, ValueError):
        return None
    start = _raw_start(span)
    if start <= 0 or end <= start:
        return None
    return round((end - start) / _unit_divisor(start) * 1000, 1)


def _span_kind(span: dict) -> Optional[str]:
    k = _attr_map(span).get(KIND_ATTR)
    return k if isinstance(k, str) else None


# ---------------------------------------------------------------------------
# 排序:父 span 建树 + 深度优先,稳序(start, span_id);孤儿/环兜底为根
# ---------------------------------------------------------------------------
def _order_spans(spans: list[dict]) -> list[dict]:
    by_id = {s_id: s for s in spans if (s_id := _span_id(s))}
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []
    for s in spans:
        pid = _parent_id(s)
        if pid and pid in by_id and pid != _span_id(s):
            children.setdefault(pid, []).append(s)
        else:
            roots.append(s)
    order_key = lambda s: (_raw_start(s), _span_id(s))  # noqa: E731
    roots.sort(key=order_key)
    for lst in children.values():
        lst.sort(key=order_key)
    out: list[dict] = []
    seen: set[int] = set()

    def visit(s: dict) -> None:
        if id(s) in seen:
            return
        seen.add(id(s))
        out.append(s)
        for c in children.get(_span_id(s), []):
            visit(c)

    for r in roots:
        visit(r)
    for s in sorted(spans, key=order_key):  # 环引用兜底:未被树覆盖的按全局序补齐
        visit(s)
    return out


# ---------------------------------------------------------------------------
# 映射:span → 决策点(形态与插桩器对齐,Fork 回放的前提)
# ---------------------------------------------------------------------------
def _dp_from_span(
    trace_id: str, branch_id: str, step: int, span: dict, prev_dp_id: Optional[str]
) -> m.DecisionPoint:
    kind_attr = _span_kind(span)
    attrs = _attr_map(span)
    name = span.get("name") or "span"
    if kind_attr == SPAN_KIND_LLM:
        dp_kind, agent_id = m.KIND_LLM, str(name)
        input_context = _llm_input(attrs)
        output = _llm_output(attrs)
    else:
        dp_kind, agent_id = m.KIND_TOOL, str(attrs.get("tool.name") or name)
        input_context = _tool_input(attrs, str(name))
        output = _tool_output(attrs)
    meta: dict = {"imported": True}
    if _span_id(span):
        meta["imported_span_id"] = _span_id(span)
    lat = _duration_ms(span)
    if lat is not None:
        meta["latency_ms"] = lat
    return m.DecisionPoint(
        id=m.new_id("dp"),
        trace_id=trace_id,
        branch_id=branch_id,
        step_index=step,
        kind=dp_kind,
        agent_id=agent_id,
        input_context=input_context,
        output=output,
        cause_edge=[prev_dp_id] if prev_dp_id else [],
        meta=meta,
    )


def _llm_input(attrs: dict) -> dict:
    return {
        "messages": _messages_from(attrs, "llm.input_messages"),
        "model": attrs.get("llm.model_name") or attrs.get("llm.model"),
        "params": _json_dict(attrs.get("llm.invocation_parameters")),
    }


def _llm_output(attrs: dict) -> dict:
    """输出对齐 _shape_llm / _shape_response:{"content", "tool_calls"}。"""
    msgs = _messages_from(attrs, "llm.output_messages")
    content, tool_calls = None, []
    for msg in msgs:
        if (msg.get("role") or "assistant") == "assistant":
            content = msg.get("content")
            tool_calls = msg.get("tool_calls") or []
            break
    if content is None and msgs:
        content = msgs[-1].get("content")
    return {"content": content, "tool_calls": tool_calls or _json_list(attrs.get("llm.tool_calls"))}


def _tool_input(attrs: dict, span_name: str) -> dict:
    return {
        "tool": attrs.get("tool.name") or span_name,
        "args": _json_any(attrs.get("tool.parameters")),
    }


def _tool_output(attrs: dict) -> dict:
    """输出对齐 Serializer.tool_output / _reconstruct_tool:{"result", "is_error"}。"""
    return {
        "result": _json_any(attrs.get("tool.return_value")),
        "is_error": bool(attrs.get("tool.is_error")),
    }


# ---------------------------------------------------------------------------
# 属性值规整:JSON 字符串二次解析(失败降级为原文本)
# ---------------------------------------------------------------------------
def _json_any(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v
    return v


def _json_dict(v: Any) -> dict:
    d = _json_any(v)
    return d if isinstance(d, dict) else {}


def _json_list(v: Any) -> list:
    d = _json_any(v)
    return d if isinstance(d, list) else []


def _messages_from(attrs: dict, prefix: str) -> list[dict]:
    """读取消息列表,支持两种 OpenInference 编码:

    1. 整体属性(JSON 字符串或已解析列表),元素形如 {"message": {role, content, tool_calls}} 或 {role, content};
    2. 扁平点分键:`prefix.<i>.message.role` / `prefix.<i>.message.content`。
    """
    raw = _json_list(attrs.get(prefix))
    if raw:
        return [_msg_record(x) for x in raw]
    per_idx: dict[int, dict] = {}
    for k, v in attrs.items():
        if not isinstance(k, str) or not k.startswith(prefix + "."):
            continue
        parts = k[len(prefix) + 1 :].split(".")
        if not parts or not parts[0].isdigit():
            continue
        slot = per_idx.setdefault(int(parts[0]), {})
        slot[".".join(parts[1:])] = v
    out = []
    for i in sorted(per_idx):
        slot = per_idx[i]
        rec: dict = {
            "role": slot.get("message.role", "user"),
            "content": slot.get("message.content"),
        }
        if slot.get("message.tool_calls"):  # 部分导出把 tool_calls 整体挂在扁平键上
            rec["tool_calls"] = slot["message.tool_calls"]
        out.append(rec)
    return out


def _msg_record(msg: Any) -> dict:
    role = _msg_field(msg, "role")
    content = _msg_field(msg, "content")
    tool_calls = _msg_field(msg, "tool_calls")
    rec: dict = {"role": role, "content": content}
    if tool_calls:  # assistant 的工具调用透传,回放时 reconstruct 需要
        rec["tool_calls"] = tool_calls
    return rec


def _msg_field(msg: Any, field: str) -> Any:
    if isinstance(msg, dict):
        inner = msg.get("message")
        if isinstance(inner, dict):
            return inner.get(field)
        return msg.get(field) or msg.get(f"message.{field}")
    return None
