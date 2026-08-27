"""Fork 引擎测试:发起边界、注入修改、嵌套、并发(spec `fork`)。"""
from __future__ import annotations

import threading

import pytest

from agent_inspect._context import MODE_FORK, ExecutionCursor, reset_cursor, set_cursor
from agent_inspect._models import ORIGIN_FORK, ORIGIN_RECORD
from agent_inspect.fork import ForkError, Modification

from tests.conftest import FakeLLM, run_agent


def _record(env, n: int, scripted: list):
    """录制 n 步,返回 (fake_llm, outs, trace, root_branch)。"""
    llm = FakeLLM(scripted)
    outs = run_agent(env.interceptor, n, llm)
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]
    return llm, outs, trace, root


def _fork_cursor(env, trace, root, from_step, mods=None, dry_run=False):
    branch, plan = env.fork.request_fork(
        trace_id=trace.id,
        from_branch=root.id,
        from_step=from_step,
        modifications=mods,
        dry_run=dry_run,
    )
    cursor = ExecutionCursor(
        trace_id=trace.id,
        branch_id=branch.id,
        mode=MODE_FORK,
        replay_branch_id=root.id,
        branch_from_step=plan.branch_from_step,
        dry_run=dry_run,
    )
    return cursor, branch


def _enter(cursor):
    set_cursor(cursor)


def _exit():
    reset_cursor(set_cursor(None))


def test_fork_creates_branch_with_origin(env):
    """从决策点发起分支:parent/origin 正确(spec fork.发起新分支)。"""
    _, _, trace, root = _record(env, 3, ["a", "b", "c"])
    branch, _plan = env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=1)
    assert branch.parent_branch_id == root.id
    assert branch.branch_from_step == 1
    assert branch.origin == ORIGIN_FORK
    branches = env.store.list_branches(trace.id)
    assert len(branches) == 2
    assert branches[0].origin == ORIGIN_RECORD  # 原 trace 不受影响


def test_fork_at_root_has_empty_prefix(env):
    """根决策点 Fork:前缀为空,后缀从该点真调(spec fork.在根决策点 Fork)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    cursor, _branch = _fork_cursor(env, trace, root, 0)
    _enter(cursor)
    llm2 = FakeLLM(["X", "Y"])
    outs = run_agent(env.interceptor, 2, llm2)
    _exit()
    assert outs == ["X", "Y"]  # 无回放,全部真调
    assert llm2.calls == 2


def test_fork_empty_trace_rejected(env):
    """空链 Fork 被拒 + 可观测原因(spec fork.空链 Fork)。"""
    trace, _root = env.store.create_trace_with_root("agent")
    root = env.store.list_branches(trace.id)[0]
    with pytest.raises(ForkError) as ei:
        env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=0)
    assert "empty trace" in str(ei.value)
    assert len(env.store.list_branches(trace.id)) == 1  # 不创建无起点分支


def test_fork_out_of_range_rejected(env):
    _, _, trace, root = _record(env, 2, ["a", "b"])
    with pytest.raises(ForkError):
        env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=99)


def test_nested_fork_replays_parent_branch(env):
    """嵌套 Fork:fork 一个 fork 产物,前缀沿用该分支记录回放(spec fork.嵌套 Fork)。"""
    _, _, trace, root = _record(env, 3, ["a", "b", "c"])
    # 第一层 fork:from_step=1 → step0 回放、step1 真调 X(需 2 步消费)
    c1, b1 = _fork_cursor(env, trace, root, 1)
    _enter(c1)
    llm1 = FakeLLM(["X"])
    outs1 = run_agent(env.interceptor, 2, llm1)
    _exit()
    assert outs1 == ["a", "X"]  # step0 回放原始 a、step1 真调 X 记入 b1
    assert llm1.calls == 1
    # 第二层 fork b1:from_step=2 → 回放 step0(a)、step1(X),真调 step2→Z
    c2, b2 = _fork_cursor(env, trace, b1, 2)
    _enter(c2)
    llm2 = FakeLLM(["Z"])
    outs = run_agent(env.interceptor, 3, llm2)
    _exit()
    # 嵌套前缀读的是第一层分支的记录输出(X),而非原始 a
    assert outs == ["a", "X", "Z"]
    assert llm2.calls == 1


def test_fork_inject_prompt(env):
    """修改 prompt 生效(spec 注入修改.修改 prompt)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    mod = Modification(step=0, field="input_context.messages[0].content", value="INJECTED")
    cursor, _b = _fork_cursor(env, trace, root, 0, mods=[mod])
    _enter(cursor)

    seen = {}

    def _make_modified(inp):
        seen.update(inp)
        return lambda: "REAL"

    env.interceptor.sroute(
        kind="llm",
        agent_id="fake-llm",
        input_context={"messages": [{"role": "user", "content": "hi"}], "model": "fake"},
        call=lambda: "REAL",
        reconstruct=lambda d: d["content"] if d else None,
        shape_output=lambda x: {"content": x},
        make_modified_call=_make_modified,
    )
    _exit()
    assert seen["messages"][0]["content"] == "INJECTED"


def test_fork_inject_tool_output_no_real_call(env):
    """修改工具返回:不再真实调用该工具(spec 注入修改.修改工具返回)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    mod = Modification(step=0, field="output", value={"result": "FAKE_RESULT"})
    cursor, _b = _fork_cursor(env, trace, root, 0, mods=[mod])
    _enter(cursor)
    llm = FakeLLM(["SHOULD_NOT_CALL"])
    out = run_agent(env.interceptor, 1, llm)[0]
    _exit()
    assert out == {"result": "FAKE_RESULT"}
    assert llm.calls == 0  # 注入工具返回:不真调


def test_fork_inject_params(env):
    """修改参数生效(spec 注入修改.修改参数)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    mod = Modification(step=0, field="input_context.params.temperature", value=0.9)
    cursor, _b = _fork_cursor(env, trace, root, 0, mods=[mod])
    _enter(cursor)

    seen = {}

    def _make_modified(inp):
        seen.update(inp)
        return lambda: "R"

    env.interceptor.sroute(
        kind="llm",
        agent_id="fake-llm",
        input_context={"messages": [], "model": "fake", "params": {"temperature": 0.1}},
        call=lambda: "R",
        reconstruct=lambda d: d["content"] if d else None,
        shape_output=lambda x: {"content": x},
        make_modified_call=_make_modified,
    )
    _exit()
    assert seen["params"]["temperature"] == 0.9


def test_branch_enumeration_origin_labels(env):
    """分支枚举含 origin(record|fork)(spec 分支图可枚举与并排)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=1)
    branches = env.store.list_branches(trace.id)
    assert {b.origin for b in branches} == {ORIGIN_RECORD, ORIGIN_FORK}


def test_concurrent_branch_writes_safe(env):
    """多分支并发写入不损坏(spec 分支执行隔离.并发分支写入安全)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    c1, b1 = _fork_cursor(env, trace, root, 1)
    c2, b2 = _fork_cursor(env, trace, root, 1)
    results = {}

    def run_branch(name, cursor, val):
        _enter(cursor)
        try:
            llm = FakeLLM([val])
            run_agent(env.interceptor, 2, llm)  # step0 回放、step1 真调 val
            results[name] = True
        finally:
            _exit()

    t1 = threading.Thread(target=run_branch, args=("b1", c1, "X"))
    t2 = threading.Thread(target=run_branch, args=("b2", c2, "Y"))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert results == {"b1": True, "b2": True}
    p1 = env.store.get_decision_points(trace.id, b1.id)
    p2 = env.store.get_decision_points(trace.id, b2.id)
    assert [x.output for x in p1] == [{"content": "X"}]
    assert [x.output for x in p2] == [{"content": "Y"}]
