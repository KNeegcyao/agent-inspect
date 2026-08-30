"""Recorder 测试:增量快照、大对象去重、粒度档(spec `recording`)。"""
from __future__ import annotations

from agent_inspect._models import DecisionPoint, new_id
from agent_inspect.recorder.dedup import Dedup
from agent_inspect.recorder.context_snap import ContextSnap

from tests.conftest import FakeLLM, run_agent


def _mk_dp(branch_id: str, step: int, ctx: dict, out: dict | None = None) -> DecisionPoint:
    return DecisionPoint(
        id=new_id("dp"),
        trace_id="tr_test",
        branch_id=branch_id,
        step_index=step,
        kind="llm",
        agent_id="fake",
        input_context=ctx,
        output=out,
    )


def test_incremental_snapshot_shared_prefix_stored_once(env):
    """增量:共享前缀只存一次,单点回放仍能还原全量(spec 增量上下文快照)。"""
    branch_id = "br_snap"
    base_ctx = {
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}],
        "model": "fake",
        "params": {"temperature": 0.0},
    }
    d0 = _mk_dp(branch_id, 0, dict(base_ctx), {"content": "a"})
    d1 = _mk_dp(branch_id, 1, dict(base_ctx), {"content": "b"})
    d2 = _mk_dp(branch_id, 2, {**base_ctx, "params": {"temperature": 0.7}}, {"content": "c"})

    snap = ContextSnap()
    for d in (d0, d1, d2):
        # 模拟 persist 顺序:先快照、再写 dp 行(供 last_step_before 定位前一步)
        snap.record(env.store, d)
        env.store.write_decision_point(d)
    # 行内 input_context 全部替换为 diff 引用
    assert all("context_diff_ref" in d.input_context for d in (d0, d1, d2))
    # 仅第一条存全量;后两条为 diff → 快照体积显著小于全量
    rows = env.store.get_context_diffs(branch_id, 2)
    full_rows = [r for r in rows if r[1] is None]
    assert len(full_rows) == 1

    # 单点重建:d0/d1/d2 都应还原为各自全量
    assert snap.reconstruct(env.store, branch_id, 0) == base_ctx
    assert snap.reconstruct(env.store, branch_id, 1) == base_ctx
    assert snap.reconstruct(env.store, branch_id, 2) == {**base_ctx, "params": {"temperature": 0.7}}


def test_dedup_same_large_output_stored_once(env):
    """大对象相同 → 存一份、引用关联(spec 大对象去重存储.相同输出去重)。"""
    big = {"data": "x" * 10000}
    dedup = Dedup(threshold=4096)
    ref1 = dedup.maybe_store(env.store, big, "dev")
    ref2 = dedup.maybe_store(env.store, big, "dev")
    assert ref1 == ref2 and "blob_ref" in ref1
    assert env.store.get_blob(ref1["blob_ref"]) is not None


def test_dedup_different_outputs_kept_separately(env):
    """大对象不同 → 各自留存(spec 差异输出各自留存)。"""
    dedup = Dedup(threshold=16)
    ref1 = dedup.maybe_store(env.store, {"a": "1" * 50}, "dev")
    ref2 = dedup.maybe_store(env.store, {"a": "2" * 50}, "dev")
    assert ref1["blob_ref"] != ref2["blob_ref"]


def test_prod_mode_stores_hash_without_full_text(env):
    """prod 档:大对象 hash 不存全文,行内只有引用 + 摘要(spec 可配记录粒度.轻量记录档)。"""
    big = {"data": "y" * 200}
    dedup = Dedup(threshold=4096)
    ref = dedup.maybe_store(env.store, big, "prod")
    assert "blob_ref" in ref and "summary" in ref
    assert len(ref["summary"]) < 300  # 摘要有界


def test_crash_does_not_lose_persisted(env):
    """崩溃不丢已完成者(spec 异常中止前已登记者不丢)。"""
    llm = FakeLLM(["a", "b"])
    run_agent(env.interceptor, 1, llm)
    try:
        raise RuntimeError("simulated crash mid-agent")
    except RuntimeError:
        pass
    trace = env.store.list_traces()[0]
    branch = env.store.list_branches(trace.id)[0]
    points = env.store.get_decision_points(trace.id, branch.id)
    assert len(points) == 1  # 已登记的 dp 仍在 store


def test_cause_edge_persisted(env):
    """因果边落库(spec 因果关系可追溯)。"""
    llm = FakeLLM(["a", "b", "c"])
    run_agent(env.interceptor, 3, llm)
    trace = env.store.list_traces()[0]
    branch = env.store.list_branches(trace.id)[0]
    points = env.store.get_decision_points(trace.id, branch.id)
    assert points[1].cause_edge == [points[0].id]
    assert points[2].cause_edge == [points[1].id]


# ---- 同时钟刻度排序确定性(回归:Windows time.time() 精度可达 ~15.6ms)----


def test_same_tick_traces_newest_first(monkeypatch, env):
    """同一时钟刻度创建的多条 trace:list_traces 按插入序破平局,新者在先。"""
    import agent_inspect._models as m

    monkeypatch.setattr(m, "now", lambda: 1234.0)  # 所有 started_at 完全相等
    t1, _ = env.store.create_trace_with_root("a")
    t2, _ = env.store.create_trace_with_root("b")
    t3, _ = env.store.create_trace_with_root("c")
    assert [t.id for t in env.store.list_traces()] == [t3.id, t2.id, t1.id]


def test_same_tick_child_traces_insertion_order(monkeypatch, env):
    """同一时钟刻度创建的子 trace:list_child_traces 按插入序破平局。"""
    import agent_inspect._models as m

    monkeypatch.setattr(m, "now", lambda: 1234.0)
    parent, _ = env.store.create_trace_with_root("parent")
    c1, _ = env.store.create_trace_with_root("c1", parent_trace_id=parent.id)
    c2, _ = env.store.create_trace_with_root("c2", parent_trace_id=parent.id)
    assert [t.id for t in env.store.list_child_traces(parent.id)] == [c1.id, c2.id]


def test_same_tick_breakpoints_insertion_order(monkeypatch, env):
    """同一时钟刻度创建的断点:list_breakpoints 按插入序破平局。"""
    import agent_inspect._models as m

    monkeypatch.setattr(m, "now", lambda: 1234.0)
    trace, _ = env.store.create_trace_with_root("a")
    bp1 = env.store.add_breakpoint(trace.id, kind="llm")
    bp2 = env.store.add_breakpoint(trace.id, condition="x")
    assert [b.id for b in env.store.list_breakpoints(trace.id)] == [bp1.id, bp2.id]


def test_delete_trace_cascades_and_isolates(env):
    """trace 删除:级联清分支/决策点/断点;其它 trace 完好(spec recording.trace 删除管理)。"""
    from agent_inspect._models import new_id

    t1 = env.store.create_trace_with_root("a")
    t2 = env.store.create_trace_with_root("b")
    # t1:fork 分支 + 决策点 + 上下文 diff + 断点
    tid1, root1 = t1[0].id, t1[1].id
    d0 = _mk_dp(root1, 0, {"messages": [{"role": "user", "content": "hello"}]}, {"content": "a"})
    d0.trace_id = tid1
    env.store.write_decision_point(d0)
    br2 = env.store.create_branch(tid1, root1, 1, "fork", None)  # root1 已是 id 字符串
    d1 = _mk_dp(br2.id, 1, {"messages": [{"role": "user", "content": "hello world"}]}, {"content": "b"})
    d1.trace_id = tid1
    env.store.write_decision_point(d1)
    env.store.write_context_diff(new_id("ctx"), br2.id, 1, 0, [{"op": "replace", "path": [], "value": {}}])
    env.store.add_breakpoint(t1[0].id, kind="llm")
    # t2:一个决策点(必须完好)
    tid2, root2 = t2[0].id, t2[1].id
    dkeep = _mk_dp(root2, 0, {}, {"content": "keep"})
    dkeep.trace_id = tid2
    env.store.write_decision_point(dkeep)

    assert env.store.delete_trace(t1[0].id) is True
    assert env.store.delete_trace(t1[0].id) is False  # 再删 → 不存在
    assert env.store.get_trace(t1[0].id) is None
    assert env.store.list_branches(t1[0].id) == []
    assert env.store.get_decision_points(t1[0].id, root1) == []
    assert env.store.get_decision_points(t1[0].id, br2.id) == []
    assert env.store.list_breakpoints(t1[0].id) == []
    # 隔离:t2 完好
    assert env.store.get_trace(t2[0].id) is not None
    assert len(env.store.get_decision_points(t2[0].id, root2)) == 1
