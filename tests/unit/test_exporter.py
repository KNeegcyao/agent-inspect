"""外部 span 导出测试(spec `trace-export`)。

覆盖:决策点 → span 逐字段逆映射、顺序与父子链、空链导出、
往返等价(导出 → 导入 → kind/顺序/输入输出一致)。
"""
from __future__ import annotations

import json

import pytest

from agent_inspect.exporter import TraceExportError, export_trace
from agent_inspect.importer import import_trace

from tests.conftest import FakeLLM, run_agent

NS = 1_720_000_000_000_000_000


def _seed_chain(env):
    """导入一条 llm(含 tool_calls)→ tool → llm 的链路作为导出素材,返回 (trace_id, root_branch_id)。"""
    attrs1 = {
        "openinference.span.kind": "LLM",
        "llm.model_name": "gpt-test",
        "llm.input_messages": json.dumps([{"message": {"role": "user", "content": "1+2?"}}]),
        "llm.output_messages": json.dumps(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}
                        ],
                    }
                }
            ]
        ),
        "llm.invocation_parameters": json.dumps({"temperature": 0.1}),
    }
    attrs2 = {
        "openinference.span.kind": "TOOL",
        "tool.name": "add",
        "tool.parameters": json.dumps({"x": 1, "y": 2}),
        "tool.return_value": json.dumps(3),
    }
    attrs3 = {
        "openinference.span.kind": "LLM",
        "llm.model_name": "gpt-test",
        "llm.input_messages": json.dumps([{"message": {"role": "user", "content": "1+2?"}}]),
        "llm.output_messages": json.dumps([{"message": {"role": "assistant", "content": "3"}}]),
    }
    spans = [
        {"span_id": f"s{i}", "parent_span_id": None if i == 0 else f"s{i-1}",
         "name": f"sp{i}", "start_time": NS + i * 1_000_000,
         "end_time": NS + i * 1_000_000 + 500_000, "attributes": attrs}
        for i, attrs in enumerate((attrs1, attrs2, attrs3))
    ]
    res = import_trace(env.store, env.recorder, {"agent_name": "seed", "spans": spans})
    return res.trace_id, res.root_branch_id


def _attr_map(span):
    return {a["key"]: a["value"] for a in span["attributes"]}


def _str_val(v):
    return json.loads(v["stringValue"]) if isinstance(v["stringValue"], str) else v["stringValue"]


# ---------------------------------------------------------------------------
# 逆映射
# ---------------------------------------------------------------------------
def test_export_maps_llm_and_tool_fields(env):
    """LLM/工具决策点的完整输入输出映射为对应 span 属性(spec trace-export.映射)。"""
    tid, root = _seed_chain(env)
    envelope = export_trace(env.store, env.recorder, tid)
    spans = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 3
    # 工具决策点的 agent_id = tool.name(导入端约定),往返后保持一致
    assert [s["name"] for s in spans] == ["sp0", "add", "sp2"]

    llm0 = _attr_map(spans[0])
    assert llm0["openinference.span.kind"]["stringValue"] == "LLM"
    assert llm0["llm.model_name"]["stringValue"] == "gpt-test"
    in_msgs = _str_val(llm0["llm.input_messages"])
    assert in_msgs[0]["message"]["role"] == "user"
    assert in_msgs[0]["message"]["content"] == "1+2?"
    out_msgs = _str_val(llm0["llm.output_messages"])
    assert out_msgs[0]["message"]["content"] == ""
    assert out_msgs[0]["message"]["tool_calls"][0]["name"] == "add"
    assert _str_val(llm0["llm.invocation_parameters"]) == {"temperature": 0.1}

    tool = _attr_map(spans[1])
    assert tool["openinference.span.kind"]["stringValue"] == "TOOL"
    assert tool["tool.name"]["stringValue"] == "add"
    assert _str_val(tool["tool.parameters"]) == {"x": 1, "y": 2}
    assert _str_val(tool["tool.return_value"]) == 3

    # 信封头:service.name 为 trace 的 agent_name
    res_attrs = envelope["resourceSpans"][0]["resource"]["attributes"]
    assert res_attrs[0]["key"] == "service.name"
    assert res_attrs[0]["value"]["stringValue"] == "seed"


def test_export_order_and_parent_chain(env):
    """span 顺序与决策链一致,父子链逐级相连(spec trace-export.顺序一致/因果保留)。"""
    tid, root = _seed_chain(env)
    envelope = export_trace(env.store, env.recorder, tid)
    spans = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert [s["spanId"] for s in spans] == [f"{i + 1:016x}" for i in range(3)]
    assert spans[0]["parentSpanId"] == ""
    # 明确断言:每个 span 的 parent 是前一个 span
    for prev, cur in zip(spans, spans[1:]):
        assert cur["parentSpanId"] == prev["spanId"]
    # 时间单调递增
    starts = [int(s["startTimeUnixNano"]) for s in spans]
    assert starts == sorted(starts)


def test_export_empty_trace(env):
    """空链 trace 导出为不含 span 的合法导出 JSON,不产生写入(spec trace-export.空链导出)。"""
    trace, _root = env.store.create_trace_with_root("empty-agent")
    envelope = export_trace(env.store, env.recorder, trace.id)
    spans = envelope["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert spans == []
    assert len(env.store.list_traces()) == 1  # 只读:无新 trace


def test_export_missing_trace_rejected(env):
    with pytest.raises(TraceExportError):
        export_trace(env.store, env.recorder, "tr_does_not_exist")


# ---------------------------------------------------------------------------
# 往返等价
# ---------------------------------------------------------------------------
def test_roundtrip_equivalence(env):
    """导出 → 再导入:kind/顺序/输入输出与被导出链路逐一一致(spec trace-export.往返等价)。"""
    tid, root = _seed_chain(env)
    original = env.recorder.read_branch_points(tid, root)

    envelope = export_trace(env.store, env.recorder, tid)
    res = import_trace(env.store, env.recorder, envelope)
    assert res.decision_points == 3

    reimported = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert [p["kind"] for p in reimported] == [p["kind"] for p in original]
    assert [p["step_index"] for p in reimported] == [p["step_index"] for p in original]
    for a, b in zip(original, reimported):
        assert a["input_context"] == b["input_context"]
        if a["kind"] == "llm":
            # 输出在可观测层面等价(工具调用缺失与空列表同义,见 _reconstruct_llm)
            assert b["output"] == {
                "content": a["output"].get("content"),
                "tool_calls": a["output"].get("tool_calls") or [],
            }
        else:
            assert a["output"] == b["output"]


def test_roundtrip_of_recorded_run(env):
    """自录链路的往返:录制 → 导出 → 导入 → 决策点输入输出保真。"""
    llm = FakeLLM(["a", "b", "c"])
    run_agent(env.interceptor, 3, llm)
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]

    envelope = export_trace(env.store, env.recorder, trace.id, root.id)
    res = import_trace(env.store, env.recorder, envelope)

    original = env.recorder.read_branch_points(trace.id, root.id)
    reimported = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert [p["kind"] for p in reimported] == ["llm"] * 3
    for a, b in zip(original, reimported):
        # 录制助手构造的输入缺省 params 键;契约形态(Serializer.llm_input)恒含 params
        assert b["input_context"] == {
            "messages": a["input_context"].get("messages") or [],
            "model": a["input_context"].get("model"),
            "params": a["input_context"].get("params") or {},
        }
        assert b["output"] == {
            "content": a["output"].get("content"),
            "tool_calls": a["output"].get("tool_calls") or [],
        }
