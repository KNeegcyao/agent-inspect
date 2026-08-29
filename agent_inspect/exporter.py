"""trace 决策链导出:把决策点链映射为遵循 OpenInference 语义约定的 span 导出 JSON。

与 importer.py 互为逆操作(同一契约):导出产物可被导入端原样消费,重建内容等价的链路。
只读计算——输入经 resolve_dp 全量解析(diff / blob 引用先还原),不产生任何写入。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ._server.store.queries import Store
from .recorder import Recorder


class TraceExportError(Exception):
    """导出前置校验失败(trace / branch 不存在)。"""


def export_trace(
    store: Store, recorder: Recorder, trace_id: str, branch_id: Optional[str] = None
) -> dict:
    """导出一条 trace 的决策链(默认根分支)为 OTLP JSON 信封 dict。空链返回空 spans。"""
    trace = store.get_trace(trace_id)
    if trace is None:
        raise TraceExportError(f"trace {trace_id} not found")
    if branch_id is None:
        branch_id = trace.root_branch_id
    branch = store.get_branch(branch_id) if branch_id else None
    if branch is None or branch.trace_id != trace_id:
        raise TraceExportError(f"branch {branch_id!r} not found in trace {trace_id}")

    points = recorder.read_branch_points(trace_id, branch_id)
    base_ns = int(trace.started_at * 1e9)
    trace_id_hex = (trace.id.split("_", 1)[-1] or trace.id).ljust(32, "0")[:32]

    spans: list[dict] = []
    prev_span_id = ""
    for i, p in enumerate(points):
        span_id = f"{i + 1:016x}"
        start_ns = base_ns + i * 1_000_000  # 每步 +1ms,保证顺序单调
        end_ns = start_ns + int(max(p.get("meta", {}).get("latency_ms") or 1.0, 0.001) * 1e6)
        spans.append(
            {
                "traceId": trace_id_hex,
                "spanId": span_id,
                "parentSpanId": prev_span_id,  # 因果边为线性链 → span 父子链
                "name": p["agent_id"],
                "startTimeUnixNano": str(start_ns),
                "endTimeUnixNano": str(end_ns),
                "attributes": _span_attrs(p),
            }
        )
        prev_span_id = span_id

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": trace.agent_name or "agent"},
                        }
                    ]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }


# ---------------------------------------------------------------------------
# 决策点 → span 属性(与 importer._dp_from_span 严格对偶)
# ---------------------------------------------------------------------------
def _span_attrs(p: dict) -> list[dict]:
    if p["kind"] == "llm":
        return _llm_attrs(p)
    return _tool_attrs(p)


def _llm_attrs(p: dict) -> list[dict]:
    inp = p["input_context"] or {}
    out = p["output"] or {}
    input_messages = [
        {"message": _message_body(m)} for m in (inp.get("messages") or [])
    ]
    output_messages = [{"message": _message_body({"role": "assistant", **_output_fields(out)})}]
    attrs = [
        ("openinference.span.kind", "LLM"),
        ("llm.model_name", inp.get("model") or ""),
        ("llm.input_messages", _json_str(input_messages)),
        ("llm.output_messages", _json_str(output_messages)),
    ]
    if inp.get("params"):
        attrs.append(("llm.invocation_parameters", _json_str(inp["params"])))
    return _attr_array(attrs)


def _output_fields(out: dict) -> dict:
    body: dict = {"content": out.get("content")}
    if out.get("tool_calls"):
        body["tool_calls"] = out["tool_calls"]
    return body


def _message_body(msg: dict) -> dict:
    body: dict = {"role": msg.get("role") or "user", "content": msg.get("content")}
    if msg.get("tool_calls"):  # assistant 工具调用透传(回放 reconstruct 需要)
        body["tool_calls"] = msg["tool_calls"]
    return body


def _tool_attrs(p: dict) -> list[dict]:
    inp = p["input_context"] or {}
    out = p["output"] or {}
    attrs: list[tuple[str, Any]] = [
        ("openinference.span.kind", "TOOL"),
        ("tool.name", inp.get("tool") or p["agent_id"]),
        ("tool.parameters", _json_str(inp.get("args"))),
        ("tool.return_value", _json_str(out.get("result"))),
    ]
    if out.get("is_error"):
        attrs.append(("tool.is_error", True))
    return _attr_array(attrs)


def _attr_array(pairs: list[tuple[str, Any]]) -> list[dict]:
    out = []
    for key, value in pairs:
        if isinstance(value, bool):
            val = {"boolValue": value}
        else:
            val = {"stringValue": str(value)}
        out.append({"key": key, "value": val})
    return out


def _json_str(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
