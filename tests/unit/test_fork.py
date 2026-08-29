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


def _fork_cursor(env, trace, root, from_step, mods=None, dry_run=False, sandbox=None):
    branch, plan = env.fork.request_fork(
        trace_id=trace.id,
        from_branch=root.id,
        from_step=from_step,
        modifications=mods,
        dry_run=dry_run,
        sandbox=sandbox,
    )
    cursor = ExecutionCursor(
        trace_id=trace.id,
        branch_id=branch.id,
        mode=MODE_FORK,
        replay_branch_id=root.id,
        branch_from_step=plan.branch_from_step,
        dry_run=dry_run,
        sandbox=plan.sandbox,
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


def test_fork_parent_branch_not_found_rejected(env):
    """父分支不存在 → 拒绝 + 可观测原因(spec adopt-cross-trace.父分支不存在拒绝)。"""
    _, _, trace, _root = _record(env, 2, ["a", "b"])
    with pytest.raises(ForkError) as ei:
        env.fork.request_fork(trace_id=trace.id, from_branch="does-not-exist", from_step=0)
    assert "not found" in str(ei.value)
    assert len(env.store.list_branches(trace.id)) == 1  # 不落库


def test_fork_parent_branch_wrong_trace_rejected(env):
    """父分支属于另一 trace → 拒绝 + 不落库(spec adopt-cross-trace.父分支不属于目标 trace 拒绝)。"""
    # trace A:记录 a,b,c
    _, _, trace_a, root_a = _record(env, 3, ["a", "b", "c"])
    # 清空活跃游标,下一次 run_agent 新建第二条 trace(对称 set/reset,不恢复旧游标)
    _tok = set_cursor(None)
    try:
        # trace B:记录 X,Y,Z(env 单进程共享,新增第二条 trace)
        _, _, trace_b, root_b = _record(env, 3, ["X", "Y", "Z"])
    finally:
        reset_cursor(_tok)
    assert trace_a.id != trace_b.id
    # 用 trace A 的 id 发起 fork,但父分支是 trace B 的 root_b → 拒绝
    with pytest.raises(ForkError) as ei:
        env.fork.request_fork(trace_id=trace_a.id, from_branch=root_b.id, from_step=0)
    assert "belongs to trace" in str(ei.value)
    assert "not target trace" in str(ei.value)
    # 两个 trace 的分支集合都未被改动
    assert len(env.store.list_branches(trace_a.id)) == 1
    assert len(env.store.list_branches(trace_b.id)) == 1


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


# ---- Fork 副作用沙箱(spec `fork.副作用沙箱`)----


def test_fork_sandbox_tool_dry_run(env):
    """工具 dry-run:不真调 + meta.sandbox=dry-run;LLM 未配置照常真调(spec fork.副作用沙箱.工具 dry-run 模拟)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    cursor, _b = _fork_cursor(env, trace, root, 0, sandbox={"tool": "dry-run"})
    _enter(cursor)
    tool_llm = FakeLLM(["X", "Y"])
    outs_tool = run_agent(env.interceptor, 2, tool_llm, kind="tool")
    llm_llm = FakeLLM(["Z"])
    outs_llm = run_agent(env.interceptor, 1, llm_llm, kind="llm")
    _exit()
    # 工具:不真调,输出为空(与只读预览档同构)
    assert outs_tool == [None, None]
    assert tool_llm.calls == 0
    # LLM:未配置 kind → 照常真调
    assert outs_llm == ["Z"]
    assert llm_llm.calls == 1
    # 落盘 meta.sandbox:仅工具决策点带标记
    dps = env.store.get_decision_points(trace.id, _b.id)
    tool_dps = [d for d in dps if d.kind == "tool"]
    llm_dps = [d for d in dps if d.kind == "llm"]
    assert len(tool_dps) == 2
    assert all(d.meta.get("sandbox") == "dry-run" for d in tool_dps)
    assert all("sandbox" not in d.meta for d in llm_dps)


def test_fork_sandbox_tool_block(env):
    """工具 block:不真调 + meta.sandbox=blocked(spec fork.副作用沙箱.工具 block 阻止)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    cursor, _b = _fork_cursor(env, trace, root, 0, sandbox={"tool": "block"})
    _enter(cursor)
    tool_llm = FakeLLM(["X"])
    outs = run_agent(env.interceptor, 1, tool_llm, kind="tool")
    _exit()
    assert outs == [None]
    assert tool_llm.calls == 0
    dps = env.store.get_decision_points(trace.id, _b.id)
    assert dps[0].meta.get("sandbox") == "blocked"


def test_fork_sandbox_default_and_allow_real_call(env):
    """未配置 sandbox 或显式 allow:照常真调,行为与无沙箱一致(spec fork.副作用沙箱.未配置保持真调)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    for sb in (None, {"tool": "allow"}):
        cursor, _b = _fork_cursor(env, trace, root, 0, sandbox=sb)
        _enter(cursor)
        llm = FakeLLM(["X"])
        outs = run_agent(env.interceptor, 1, llm, kind="tool")
        _exit()
        assert outs == ["X"]
        assert llm.calls == 1
        dps = env.store.get_decision_points(trace.id, _b.id)
        assert "sandbox" not in dps[0].meta


def test_fork_sandbox_invalid_rejected(env):
    """非法 kind / policy → ForkError 拒绝 + 不落库(spec fork.副作用沙箱.非法配置拒绝)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    with pytest.raises(ForkError) as ei:
        env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=0, sandbox={"llm": "nope"})
    assert "invalid sandbox policy" in str(ei.value)
    with pytest.raises(ForkError) as ei:
        env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=0, sandbox={"memory": "block"})
    assert "invalid sandbox kind" in str(ei.value)
    # 两种非法配置都不落库
    assert len(env.store.list_branches(trace.id)) == 1


# ---- LLM 决策点沙箱(spec fork.LLM 决策点沙箱)----


def test_fork_sandbox_llm_dry_run(env):
    """LLM dry-run:不真调 + meta.sandbox=dry-run;工具未配置照常真调(spec fork.LLM 决策点沙箱.LLM dry-run 模拟)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    cursor, _b = _fork_cursor(env, trace, root, 0, sandbox={"llm": "dry-run"})
    _enter(cursor)
    llm = FakeLLM(["X", "Y"])
    outs_llm = run_agent(env.interceptor, 2, llm)
    tool_llm = FakeLLM(["Z"])
    outs_tool = run_agent(env.interceptor, 1, tool_llm, kind="tool")
    _exit()
    # LLM:dry-run → 不真调,输出为空
    assert outs_llm == [None, None]
    assert llm.calls == 0
    # 工具:未配置 kind → 照常真调
    assert outs_tool == ["Z"]
    assert tool_llm.calls == 1
    # 落盘 meta.sandbox:仅 LLM 决策点带标记
    dps = env.store.get_decision_points(trace.id, _b.id)
    llm_dps = [d for d in dps if d.kind == "llm"]
    tool_dps = [d for d in dps if d.kind == "tool"]
    assert len(llm_dps) == 2
    assert all(d.meta.get("sandbox") == "dry-run" for d in llm_dps)
    assert len(tool_dps) == 1
    assert "sandbox" not in tool_dps[0].meta


def test_fork_sandbox_llm_block(env):
    """LLM block:不真调 + meta.sandbox=blocked(spec fork.LLM 决策点沙箱.LLM block 阻止)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    cursor, _b = _fork_cursor(env, trace, root, 0, sandbox={"llm": "block"})
    _enter(cursor)
    llm = FakeLLM(["X"])
    outs = run_agent(env.interceptor, 1, llm)
    _exit()
    assert outs == [None]
    assert llm.calls == 0
    dps = env.store.get_decision_points(trace.id, _b.id)
    llm_dps = [d for d in dps if d.kind == "llm"]
    assert len(llm_dps) == 1
    assert llm_dps[0].meta.get("sandbox") == "blocked"


def test_fork_sandbox_llm_tool_mixed(env):
    """混合配置 {llm: block, tool: allow}:LLM 拦下、工具照常真调(spec fork.LLM 决策点沙箱.混合配置按 kind 独立生效)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    cursor, _b = _fork_cursor(env, trace, root, 0, sandbox={"llm": "block", "tool": "allow"})
    _enter(cursor)
    llm = FakeLLM(["X"])
    outs_llm = run_agent(env.interceptor, 1, llm)
    tool_llm = FakeLLM(["Z"])
    outs_tool = run_agent(env.interceptor, 1, tool_llm, kind="tool")
    _exit()
    assert outs_llm == [None]
    assert llm.calls == 0
    assert outs_tool == ["Z"]
    assert tool_llm.calls == 1
    dps = env.store.get_decision_points(trace.id, _b.id)
    llm_dps = [d for d in dps if d.kind == "llm"]
    tool_dps = [d for d in dps if d.kind == "tool"]
    assert llm_dps[0].meta.get("sandbox") == "blocked"
    assert "sandbox" not in tool_dps[0].meta


def test_fork_sandbox_llm_default_real_call(env):
    """LLM 未配置 sandbox 或显式 allow:照常真调(spec fork.LLM 决策点沙箱.LLM 未配置保持真调)。"""
    _, _, trace, root = _record(env, 2, ["a", "b"])
    for sb in (None, {"llm": "allow"}):
        cursor, _b = _fork_cursor(env, trace, root, 0, sandbox=sb)
        _enter(cursor)
        llm = FakeLLM(["X"])
        outs = run_agent(env.interceptor, 1, llm)
        _exit()
        assert outs == ["X"]
        assert llm.calls == 1
        dps = env.store.get_decision_points(trace.id, _b.id)
        llm_dps = [d for d in dps if d.kind == "llm"]
        assert "sandbox" not in llm_dps[0].meta
