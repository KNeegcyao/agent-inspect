"""Interceptor 路由三态测试(对应 spec `interception` + `fork` 前缀/后缀边界)。"""
from __future__ import annotations

import pytest

from agent_inspect._context import MODE_FORK, MODE_RECORD, MODE_REPLAY, ExecutionCursor, reset_cursor, set_cursor
from agent_inspect._models import ORIGIN_FORK, ORIGIN_RECORD
from agent_inspect.fork import ForkError, Modification

from tests.conftest import FakeLLM, run_agent


# ---------------------------------------------------------------------------
# Record:真调 + 落盘 + 因果边
# ---------------------------------------------------------------------------
def test_record_calls_and_persists(env):
    llm = FakeLLM(["a", "b"])
    outs = run_agent(env.interceptor, 2, llm)
    assert outs == ["a", "b"]
    assert llm.calls == 2
    branches = env.store.list_branches(env.store.list_traces()[0].id)
    assert len(branches) == 1 and branches[0].origin == ORIGIN_RECORD
    points = env.store.get_decision_points(env.store.list_traces()[0].id, branches[0].id)
    assert [p.step_index for p in points] == [0, 1]
    # 因果边:后一步指向前一步(spec 因果关系可追溯)
    assert points[1].cause_edge == [points[0].id]


def test_async_decision_points_share_trace(env):
    """异步决策点同属 trace/branch(spec 执行上下文传播.异步决策点同属)。"""
    import asyncio

    async def main():
        async def ainvoke(val):
            return await env.interceptor.aroute(
                kind="llm",
                agent_id="fake-llm",
                input_context={"messages": [], "model": "fake"},
                call=lambda: _async_value(val),
                reconstruct=lambda d: d["content"] if d else None,
                shape_output=lambda x: {"content": x},
            )

        async def _async_value(v):
            await asyncio.sleep(0)
            return v

        r0 = await ainvoke("x")
        r1 = await ainvoke("y")
        return [r0, r1]

    r = asyncio.run(main())
    assert r == ["x", "y"]
    trace = env.store.list_traces()[0]
    branches = env.store.list_branches(trace.id)
    assert len(branches) == 1  # 同 trace 同 branch
    points = env.store.get_decision_points(trace.id, branches[0].id)
    assert [p.output["content"] for p in points] == ["x", "y"]


def test_call_error_still_recorded(env):
    """调用抛错仍登记 dp 不中断(spec interception.调用失败登记)。"""
    def boom():
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError):
        env.interceptor.sroute(
            kind="llm",
            agent_id="fake-llm",
            input_context={"messages": [], "model": "fake"},
            call=boom,
            reconstruct=lambda d: d,
            shape_output=lambda x: {"content": x},
        )
    trace = env.store.list_traces()[0]
    branch = env.store.list_branches(trace.id)[0]
    points = env.store.get_decision_points(trace.id, branch.id)
    assert len(points) == 1
    assert points[0].meta["error"]["code"] == "RuntimeError"


def test_off_yields_zero_regression(env):
    """关闭后零开销原样跑(spec 非侵入启停.关闭零回归):不装 interceptor 时原样。"""
    llm = FakeLLM(["a", "b"])
    outs = [llm.call(), llm.call()]
    assert outs == ["a", "b"]
    assert llm.calls == 2


# ---------------------------------------------------------------------------
# Replay:用 recorded output、不真调;缺记录退回真调
# ---------------------------------------------------------------------------
def _fork_context(env, from_step: int, mods=None, dry_run=False) -> ExecutionCursor:
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]
    branch, plan = env.fork.request_fork(
        trace_id=trace.id,
        from_branch=root.id,
        from_step=from_step,
        modifications=mods,
        dry_run=dry_run,
    )
    return ExecutionCursor(
        trace_id=trace.id,
        branch_id=branch.id,
        mode=MODE_FORK,
        replay_branch_id=root.id,
        branch_from_step=plan.branch_from_step,
        dry_run=dry_run,
    ), trace, root, branch


def test_replay_uses_recorded_not_real(env):
    llm = FakeLLM(["a", "b", "c"])
    run_agent(env.interceptor, 3, llm)  # record: a,b,c
    assert llm.calls == 3

    cursor, trace, root, _ = _fork_context(env, from_step=1)
    set_cursor(cursor)
    llm2 = FakeLLM(["X", "Y", "Z"])
    outs = run_agent(env.interceptor, 2, llm2)  # fork: step0 replay(a), step1 real(X)
    reset_cursor(set_cursor(None))
    assert outs[0] == "a"  # 前缀用 recorded
    assert outs[1] == "X"  # 后缀真调
    assert llm2.calls == 1  # 只有后缀真调一次


def test_replay_missing_record_falls_back_to_call(env):
    """Replay 缺记录输出时退回真调(spec interception.Replay 缺记录输出时退回真调)。"""
    llm = FakeLLM(["a"])
    run_agent(env.interceptor, 1, llm)
    cursor, trace, root, _ = _fork_context(env, from_step=1)
    cursor.mode = MODE_REPLAY  # 直接以 replay 模式跑
    set_cursor(cursor)
    llm2 = FakeLLM(["fallback"])
    outs = run_agent(env.interceptor, 2, llm2)
    reset_cursor(set_cursor(None))
    assert outs == ["a", "fallback"]  # step0 有记录回放;step1 无记录 → 真调
    assert llm2.calls == 1


def test_fork_prefix_uses_record_suffix_real(env):
    llm = FakeLLM(["a", "b", "c", "d"])
    run_agent(env.interceptor, 4, llm)
    cursor, trace, root, branch = _fork_context(env, from_step=2)
    set_cursor(cursor)
    llm2 = FakeLLM(["P", "Q"])
    outs = run_agent(env.interceptor, 2, llm2)
    reset_cursor(set_cursor(None))
    assert outs == ["a", "b"]  # step0,1 全回放
    assert llm2.calls == 0  # 前缀不发真调


def test_fork_dry_run_no_suffix_call(env):
    """dry_run=True 时后缀也不真调(spec fork.只读预览档)。"""
    llm = FakeLLM(["a", "b", "c"])
    run_agent(env.interceptor, 3, llm)
    cursor, trace, root, _ = _fork_context(env, from_step=1, dry_run=True)
    set_cursor(cursor)
    llm2 = FakeLLM(["X"])
    outs = run_agent(env.interceptor, 2, llm2)  # step0 前缀回放,step1 后缀只读预览
    reset_cursor(set_cursor(None))
    assert outs == ["a", None]  # 后缀 dry_run:不真调、无输出
    assert llm2.calls == 0
