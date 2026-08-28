"""分支并排 diff 引擎测试:链路构造、步骤对齐、字段级差异、汇总(spec `branch-diff`)。"""
from __future__ import annotations

from agent_inspect._context import MODE_FORK, ExecutionCursor, reset_cursor, set_cursor
from agent_inspect.diff import (
    FIELD_ADDED,
    FIELD_CHANGED,
    FIELD_REMOVED,
    STEP_DIFF,
    STEP_ONLY_LEFT,
    STEP_ONLY_RIGHT,
    STEP_SAME,
    build_chain,
    diff_branches,
    diff_chains,
    diff_fields,
)
from agent_inspect._models import ORIGIN_FORK, ORIGIN_RECORD

from tests.conftest import FakeLLM, run_agent


def _pt(idx, output=None, input_ctx=None, kind="llm", source_branch_id=None):
    return {
        "id": f"p{idx}",
        "step_index": idx,
        "kind": kind,
        "agent_id": "a",
        "input_context": input_ctx or {"messages": [], "model": "fake"},
        "output": output,
        "output_hash": None,
        "cause_edge": [],
        "meta": {},
        "inherited": False,
        "source_branch_id": source_branch_id,
    }


# ---- 步骤对齐(纯函数)----
def test_diff_shared_prefix_steps_same():
    """共享前缀步骤标记为相同(spec 分支步骤对齐与状态.共享前缀步骤为相同)。"""
    left = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"})]
    right = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"})]
    steps, summary = diff_chains(left, right)
    assert [s["status"] for s in steps] == [STEP_SAME, STEP_SAME]
    assert summary == {STEP_SAME: 2, STEP_DIFF: 0, STEP_ONLY_LEFT: 0, STEP_ONLY_RIGHT: 0}


def test_diff_output_diff_marks_diff_with_field():
    """输出不同 → 差异,并给出字段路径与左右取值(spec 字段级差异明细.输出字段差异)。"""
    left = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"}), _pt(2, {"content": "c"})]
    right = [_pt(0, {"content": "a"}), _pt(1, {"content": "X"}), _pt(2, {"content": "c"})]
    steps, summary = diff_chains(left, right)
    assert [s["status"] for s in steps] == [STEP_SAME, STEP_DIFF, STEP_SAME]
    assert steps[1]["fields"] == [
        {"path": "output.content", "left": "b", "right": "X", "status": FIELD_CHANGED}
    ]
    assert summary == {STEP_SAME: 2, STEP_DIFF: 1, STEP_ONLY_LEFT: 0, STEP_ONLY_RIGHT: 0}


def test_diff_only_one_side():
    """仅一侧存在的步骤标记为 only_left / only_right(spec 分支步骤对齐与状态.仅一侧存在的步骤)。"""
    left = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"}), _pt(2, {"content": "c"})]
    right = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"})]
    steps, summary = diff_chains(left, right)
    assert [s["status"] for s in steps] == [STEP_SAME, STEP_SAME, STEP_ONLY_LEFT]
    assert summary[STEP_ONLY_LEFT] == 1
    # 反向:仅右侧
    steps2, summary2 = diff_chains(right, left)
    assert [s["status"] for s in steps2] == [STEP_SAME, STEP_SAME, STEP_ONLY_RIGHT]
    assert summary2[STEP_ONLY_RIGHT] == 1


def test_diff_input_diff_marks_diff():
    """输入字段差异也计为差异,并给出输入路径(spec 字段级差异明细.输入字段差异)。"""
    a = _pt(0, {"content": "OUT"}, {"messages": [{"role": "user", "content": "hi"}], "model": "fake"})
    b = _pt(0, {"content": "OUT"}, {"messages": [{"role": "user", "content": "INJECTED"}], "model": "fake"})
    steps, _ = diff_chains([a], [b])
    assert steps[0]["status"] == STEP_DIFF
    fields = {f["path"]: f for f in steps[0]["fields"]}
    assert fields["input_context.messages[0].content"] == {
        "path": "input_context.messages[0].content",
        "left": "hi",
        "right": "INJECTED",
        "status": FIELD_CHANGED,
    }


def test_diff_same_source_branch_short_circuits():
    """同源同 step 的记录直接判 same,避免输入上下文级联扩散(spec 共享前缀应判定为 same)。"""
    a = _pt(
        0,
        {"content": "a"},
        {"messages": [{"role": "user", "content": "hi"}]},
        source_branch_id="br_shared",
    )
    b = _pt(
        0,
        {"content": "DIFFERENT"},
        {"messages": [{"role": "user", "content": "INJECTED"}]},
        source_branch_id="br_shared",
    )
    steps, _ = diff_chains([a], [b])
    assert steps[0]["status"] == STEP_SAME
    assert "fields" not in steps[0] or steps[0]["fields"] == []


def test_diff_different_source_branches_fall_back_to_content():
    """不同来源分支仍按内容比较,不短路。"""
    a = _pt(0, {"content": "a"}, source_branch_id="br_a")
    b = _pt(0, {"content": "a"}, source_branch_id="br_b")
    steps, _ = diff_chains([a], [b])
    assert steps[0]["status"] == STEP_SAME  # 内容相同仍 same
    # 内容不同时应 diff
    c = _pt(0, {"content": "a"}, source_branch_id="br_a")
    d = _pt(0, {"content": "b"}, source_branch_id="br_b")
    steps2, _ = diff_chains([c], [d])
    assert steps2[0]["status"] == STEP_DIFF


def test_diff_field_only_on_one_side():
    """字段仅一侧存在 → added / removed,不静默忽略(spec 字段级差异明细.字段仅一侧存在)。"""
    a = _pt(0, {"content": "a", "extra": 1})
    b = _pt(0, {"content": "a"})
    steps, _ = diff_chains([a], [b])
    assert steps[0]["status"] == STEP_DIFF
    fields = {f["path"]: f for f in steps[0]["fields"]}
    assert fields["output.extra"]["status"] == FIELD_REMOVED
    assert fields["output.extra"]["left"] == 1 and fields["output.extra"]["right"] is None
    # 反向:added
    steps2, _ = diff_chains([b], [a])
    fields2 = {f["path"]: f for f in steps2[0]["fields"]}
    assert fields2["output.extra"]["status"] == FIELD_ADDED
    assert fields2["output.extra"]["left"] is None and fields2["output.extra"]["right"] == 1


def test_diff_nested_path_located():
    """嵌套结构差异可定位到具体路径(spec 字段级差异明细.嵌套结构差异可定位)。"""
    a = _pt(
        0,
        {"content": "a"},
        {"messages": [{"role": "user", "content": "hi"}], "params": {"temperature": 0.1}},
    )
    b = _pt(
        0,
        {"content": "a"},
        {"messages": [{"role": "user", "content": "hi"}], "params": {"temperature": 0.9}},
    )
    steps, _ = diff_chains([a], [b])
    fields = {f["path"]: f for f in steps[0]["fields"]}
    assert fields["input_context.params.temperature"]["left"] == 0.1
    assert fields["input_context.params.temperature"]["right"] == 0.9


def test_diff_deep_nesting_collapses_at_depth_limit():
    """超深嵌套退化为单条 changed,不递归爆炸。"""
    deep = {"lvl1": {"lvl2": {"lvl3": {"lvl4": {"lvl5": {"lvl6": {"lvl7": 1}}}}}}}
    deep2 = {"lvl1": {"lvl2": {"lvl3": {"lvl4": {"lvl5": {"lvl6": {"lvl7": 2}}}}}}}
    fields = diff_fields(_pt(0, deep), _pt(0, deep2))
    assert len(fields) == 1
    assert fields[0]["status"] == FIELD_CHANGED


def test_diff_kind_mismatch_same_step():
    """同步骤类型不同也算差异(结构不同可见)。"""
    a = _pt(0, {"content": "a"}, kind="llm")
    b = _pt(0, {"content": "a"}, kind="tool")
    steps, _ = diff_chains([a], [b])
    assert steps[0]["status"] == STEP_DIFF


def test_diff_summary_counts_consistent():
    """汇总计数与对齐后总步骤数一致(spec 差异汇总.汇总计数与步骤一致)。"""
    left = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"}), _pt(2, {"content": "c"}), _pt(3, {"content": "d"})]
    right = [_pt(0, {"content": "a"}), _pt(1, {"content": "B"}), _pt(2, {"content": "c"})]
    steps, summary = diff_chains(left, right)
    assert sum(summary.values()) == len(steps)
    assert summary == {STEP_SAME: 2, STEP_DIFF: 1, STEP_ONLY_LEFT: 1, STEP_ONLY_RIGHT: 0}


# ---- 集成:真实 fork 链路 ----
def _record(env, n, scripted):
    llm = FakeLLM(scripted)
    run_agent(env.interceptor, n, llm)
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]
    return trace, root


def _fork_run(env, trace, from_branch, from_step, scripted):
    branch, _ = env.fork.request_fork(
        trace_id=trace.id, from_branch=from_branch, from_step=from_step
    )
    cursor = ExecutionCursor(
        trace_id=trace.id,
        branch_id=branch.id,
        mode=MODE_FORK,
        replay_branch_id=from_branch,
        branch_from_step=from_step,
        dry_run=False,
    )
    token = set_cursor(cursor)
    try:
        # 前缀回放 from_step 步,后缀真调 len(scripted) 步 → 链总长 from_step + len(scripted)
        run_agent(env.interceptor, from_step + len(scripted), FakeLLM(scripted))
    finally:
        reset_cursor(token)
    return branch


def test_build_chain_includes_shared_prefix(env):
    """完整链路:共享前缀(继承自父分支)+ 本分支后缀。"""
    trace, root = _record(env, 3, ["a", "b", "c"])
    branch = _fork_run(env, trace, root.id, 1, ["X", "Y"])
    assert branch.origin == ORIGIN_FORK
    chain = build_chain(env.store, env.recorder.serializer, env.recorder.context_snap, branch.id)
    steps = [p["step_index"] for p in chain]
    assert steps == [0, 1, 2]
    assert chain[0]["inherited"] is True
    assert chain[0]["output"] == {"content": "a"}
    assert [p["output"]["content"] for p in chain[1:]] == ["X", "Y"]
    # 原记录分支 origin 不变
    assert env.store.list_branches(trace.id)[0].origin == ORIGIN_RECORD


def test_build_chain_tags_source_branch_id(env):
    """完整链中每个点都标记来源分支:前缀来自父分支,后缀来自本分支。"""
    trace, root = _record(env, 3, ["a", "b", "c"])
    branch = _fork_run(env, trace, root.id, 1, ["X", "Y"])
    chain = build_chain(env.store, env.recorder.serializer, env.recorder.context_snap, branch.id)
    assert chain[0]["source_branch_id"] == root.id
    assert chain[1]["source_branch_id"] == branch.id
    assert chain[2]["source_branch_id"] == branch.id


def test_diff_fork_branches_real_chains(env):
    """两分支真实链路 diff:共享前缀 same,分叉后缀 diff(spec 并排视图呈现)."""
    trace, root = _record(env, 3, ["a", "b", "c"])
    b1 = _fork_run(env, trace, root.id, 1, ["X", "Y"])
    b2 = _fork_run(env, trace, root.id, 1, ["Z", "W"])
    # fork1 vs fork2:step0(a 共享)same,step1/2 输出不同 diff
    result = diff_branches(
        env.store, env.recorder.serializer, env.recorder.context_snap, b1.id, b2.id
    )
    assert result["branch_a"] == b1.id and result["branch_b"] == b2.id
    assert [s["status"] for s in result["steps"]] == [STEP_SAME, STEP_DIFF, STEP_DIFF]
    assert result["summary"] == {STEP_SAME: 1, STEP_DIFF: 2, STEP_ONLY_LEFT: 0, STEP_ONLY_RIGHT: 0}
    assert result["steps"][1]["fields"][0]["path"] == "output.content"
    assert result["steps"][1]["fields"][0]["left"] == "X"
    assert result["steps"][1]["fields"][0]["right"] == "Z"


def test_diff_root_vs_fork_only_one_side(env):
    """根分支多出的步骤标记 only_left(spec 分支步骤对齐与状态.仅一侧存在的步骤)。"""
    trace, root = _record(env, 3, ["a", "b", "c"])
    branch = _fork_run(env, trace, root.id, 1, ["X"])
    # root 3 步;fork 分支 2 步(0 共享 + 1 真调 X)
    result = diff_branches(
        env.store, env.recorder.serializer, env.recorder.context_snap, root.id, branch.id
    )
    statuses = [s["status"] for s in result["steps"]]
    assert statuses[0] == STEP_SAME
    assert statuses[1] == STEP_DIFF  # b vs X
    assert statuses[2] == STEP_ONLY_LEFT  # c 仅 root 有
