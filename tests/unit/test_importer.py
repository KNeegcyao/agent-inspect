"""外部 span 导出导入测试(spec `trace-import`)。

覆盖:两种输入形态等价、LLM/工具映射逐字段保真、顺序与因果边、
未知 kind 忽略计数、非法导出拒绝不落库、导入链路可 Fork(前缀回放不真调)。
"""
from __future__ import annotations

import json

import pytest

from agent_inspect._context import reset_cursor, set_cursor
from agent_inspect.importer import TraceImportError, import_trace

from tests.conftest import FakeLLM, run_agent

NS = 1_720_000_000_000_000_000  # unix 纳秒(历史时刻)


def _llm_span(span_id, parent_id=None, content="hi", out="ok", start=None, otlp=False):
    """一个 LLM span(两种编码:扁平点分键 / OTLP 属性数组)。"""
    start = start if start is not None else NS
    end = start + 12_500_000  # 12.5ms
    if otlp:
        return {
            "spanId": span_id,
            "parentSpanId": parent_id,
            "name": "ChatCompletion",
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(end),
            "attributes": [
                {"key": "openinference.span.kind", "value": {"stringValue": "LLM"}},
                {"key": "llm.model_name", "value": {"stringValue": "gpt-test"}},
                {"key": "llm.invocation_parameters", "value": {"stringValue": json.dumps({"temperature": 0.2})}},
                {"key": "llm.input_messages", "value": {"stringValue": json.dumps(
                    [{"message": {"role": "user", "content": content}}])}},
                {"key": "llm.output_messages", "value": {"stringValue": json.dumps(
                    [{"message": {"role": "assistant", "content": out}}])}},
            ],
        }
    return {
        "span_id": span_id,
        "parent_span_id": parent_id,
        "name": "ChatCompletion",
        "start_time": start,
        "end_time": end,
        "attributes": {
            "openinference.span.kind": "LLM",
            "llm.model_name": "gpt-test",
            "llm.input_messages.0.message.role": "user",
            "llm.input_messages.0.message.content": content,
            "llm.output_messages.0.message.role": "assistant",
            "llm.output_messages.0.message.content": out,
        },
    }


def _tool_span(span_id, parent_id, start=None):
    start = start if start is not None else NS + 20_000_000_000
    return {
        "span_id": span_id,
        "parent_span_id": parent_id,
        "name": "search",
        "start_time": start,
        "end_time": start + 3_000_000,
        "attributes": {
            "openinference.span.kind": "TOOL",
            "tool.name": "search",
            "tool.parameters": json.dumps({"q": "weather"}),
            "tool.return_value": json.dumps({"temp": 25}),
        },
    }


def _flat_payload(spans, agent_name=None):
    payload = {"spans": spans}
    if agent_name:
        payload["agent_name"] = agent_name
    return payload


# ---------------------------------------------------------------------------
# 形态与映射
# ---------------------------------------------------------------------------
def test_flat_form_maps_llm_and_tool(env):
    """扁平形态:LLM/工具 span 映射为决策点,输入输出逐字段保真(spec trace-import.映射)。"""
    spans = [
        _llm_span("s1", content="hi", out="reply-a"),
        _tool_span("s2", "s1"),
        _llm_span("s3", "s2", content="go on", out="reply-b", start=NS + 30_000_000_000),
    ]
    res = import_trace(env.store, env.recorder, _flat_payload(spans, agent_name="prod-agent"))
    assert res.decision_points == 3 and res.skipped == 0

    trace = env.store.get_trace(res.trace_id)
    assert trace.lifecycle == "done"
    assert trace.agent_name == "prod-agent"
    assert trace.started_at == pytest.approx(NS / 1e9)  # 最早 span 起始时间(秒)

    pts = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert [p["kind"] for p in pts] == ["llm", "tool", "llm"]
    assert [p["step_index"] for p in pts] == [0, 1, 2]
    # 因果边:线性链
    assert pts[0]["cause_edge"] == []
    assert pts[1]["cause_edge"] == [pts[0]["id"]]
    assert pts[2]["cause_edge"] == [pts[1]["id"]]

    # LLM 决策点:input_context / output 与插桩器同形
    llm0 = pts[0]
    assert llm0["agent_id"] == "ChatCompletion"
    assert llm0["input_context"]["messages"] == [{"role": "user", "content": "hi"}]
    assert llm0["input_context"]["model"] == "gpt-test"
    assert llm0["output"] == {"content": "reply-a", "tool_calls": []}
    assert llm0["meta"]["imported"] is True
    assert llm0["meta"]["imported_span_id"] == "s1"
    assert llm0["meta"]["latency_ms"] == pytest.approx(12.5)

    # 工具决策点:JSON 字符串属性二次解析
    tool = pts[1]
    assert tool["input_context"] == {"tool": "search", "args": {"q": "weather"}}
    assert tool["output"] == {"result": {"temp": 25}, "is_error": False}
    assert tool["meta"]["imported"] is True


def test_otlp_envelope_equivalent(env):
    """OTLP 信封形态:属性数组 + JSON 字符串消息,映射结果与扁平形态等价(spec trace-import.映射)。"""
    spans = [
        _llm_span("a1", content="hi", out="reply-a", otlp=True),
        _llm_span("a2", "a1", content="go", out="reply-b", start=NS + 5_000_000_000, otlp=True),
    ]
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]},
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }
    res = import_trace(env.store, env.recorder, payload)
    assert res.decision_points == 2 and res.skipped == 0
    trace = env.store.get_trace(res.trace_id)
    assert trace.agent_name == "svc"

    pts = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert [p["kind"] for p in pts] == ["llm", "llm"]
    assert pts[0]["input_context"]["messages"] == [{"role": "user", "content": "hi"}]
    assert pts[0]["input_context"]["params"] == {"temperature": 0.2}
    assert pts[0]["output"] == {"content": "reply-a", "tool_calls": []}


def test_unknown_kind_skipped_with_count(env):
    """无法识别 kind 的 span 不生成决策点,导入结果回报忽略数(spec trace-import.忽略并计数)。"""
    spans = [
        _llm_span("s1"),
        {
            "span_id": "s2",
            "name": "agent-run",
            "start_time": NS + 1_000_000,
            "end_time": NS + 2_000_000,
            "attributes": {"openinference.span.kind": "AGENT"},
        },
        {
            "span_id": "s3",
            "name": "no-kind",
            "start_time": NS + 3_000_000,
            "end_time": NS + 4_000_000,
            "attributes": {},
        },
    ]
    res = import_trace(env.store, env.recorder, _flat_payload(spans))
    assert res.decision_points == 1 and res.skipped == 2
    pts = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert [p["kind"] for p in pts] == ["llm"]


def test_dfs_order_nested_spans(env):
    """嵌套 span 树按深度优先遍历定步序(spec trace-import.顺序一致)。"""
    spans = [
        _llm_span("root", start=NS),
        _tool_span("child_a", "root", start=NS + 10_000_000_000),
        _llm_span("child_b", "child_a", start=NS + 5_000_000_000),  # 起始早于父仍按树序
    ]
    res = import_trace(env.store, env.recorder, _flat_payload(spans))
    pts = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert [p["meta"]["imported_span_id"] for p in pts] == ["root", "child_a", "child_b"]


def test_llm_output_tool_calls_passthrough(env):
    """assistant 输出中的 tool_calls 透传(ReAct 首步是带工具调用的空回复,回放 reconstruct 需要)。"""
    attrs = {
        "openinference.span.kind": "LLM",
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
    }
    spans = [
        {
            "span_id": "s1",
            "name": "llm",
            "start_time": NS,
            "end_time": NS + 1_000_000,
            "attributes": attrs,
        }
    ]
    res = import_trace(env.store, env.recorder, _flat_payload(spans))
    pts = env.recorder.read_branch_points(res.trace_id, res.root_branch_id)
    assert pts[0]["output"]["tool_calls"] == [
        {"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}
    ]
    # 输入侧(用户消息)不携带 tool_calls 键
    assert "tool_calls" not in pts[0]["input_context"]["messages"][0]


# ---------------------------------------------------------------------------
# 非法导入
# ---------------------------------------------------------------------------
def test_invalid_payloads_rejected_without_writes(env):
    """非 JSON 对象 / 缺 span 树 / 无可映射 span → 拒绝且不落库(spec trace-import.非法拒绝)。"""
    before = len(env.store.list_traces())
    with pytest.raises(TraceImportError):
        import_trace(env.store, env.recorder, "not-a-dict")
    with pytest.raises(TraceImportError):
        import_trace(env.store, env.recorder, {"foo": 1})
    with pytest.raises(TraceImportError):
        import_trace(env.store, env.recorder, {"spans": [{"name": "x", "attributes": {}}]})
    assert len(env.store.list_traces()) == before


# ---------------------------------------------------------------------------
# 导入链路参与既有调试流:Fork 前缀回放导入输出、后缀真调
# ---------------------------------------------------------------------------
def test_fork_imported_trace_replays_prefix(env):
    """对导入 trace 发起 Fork:前缀用导入输出回放(不真调),后缀真调(spec trace-import.发起 Fork)。"""
    spans = [
        _llm_span("s1", out="s0", start=NS),
        _llm_span("s2", "s1", out="s1", start=NS + 10_000_000_000),
        _llm_span("s3", "s2", out="s2", start=NS + 20_000_000_000),
    ]
    res = import_trace(env.store, env.recorder, _flat_payload(spans))
    branch, _plan = env.fork.request_fork(trace_id=res.trace_id, from_branch=res.root_branch_id, from_step=2)
    assert branch.origin == "fork"

    # 清空游标后下一次执行消费 pending fork(spec fork 与导入链路的衔接)
    _tok = set_cursor(None)
    try:
        llm = FakeLLM(["X"])
        outs = run_agent(env.interceptor, 3, llm)
    finally:
        reset_cursor(_tok)
    assert outs == ["s0", "s1", "X"]  # step0/1 回放导入输出,step2 真调
    assert llm.calls == 1
