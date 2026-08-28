"""采纳映射测试:diff 字段差异 → Fork 修改的纯映射(spec `adopt-diff-to-fork`)。

覆盖映射规则:input_context 叶子、output 整段覆盖、列表索引、removed 跳过、无差异不生成,
以及 preview_adopt 的只读语义(不创建分支)。
"""
from __future__ import annotations

from agent_inspect.adopt import adopt_modifications, preview_adopt
from agent_inspect.diff import diff_chains
from agent_inspect.fork import Modification

FIELD_ADDED = "added"
FIELD_REMOVED = "removed"
FIELD_CHANGED = "changed"


def _pt(idx, output=None, input_ctx=None, kind="llm", source="L"):
    return {
        "id": f"p{source}{idx}",
        "step_index": idx,
        "kind": kind,
        "agent_id": "a",
        "input_context": input_ctx or {"messages": [], "model": "fake"},
        "output": output,
        "output_hash": None,
        "cause_edge": [],
        "meta": {},
        "inherited": False,
        "source_branch_id": f"br_{source}_{idx}",
    }


def _diff_steps(left, right):
    steps, _ = diff_chains(left, right)
    return steps


def _adopt(left, right, steps=None):
    """构建右侧链路索引后执行采纳映射(输出整段覆盖取右侧完整 output)。"""
    diff_steps = _diff_steps(left, right)
    if steps is not None:
        want = set(steps)
        diff_steps = [s for s in diff_steps if int(s["step_index"]) in want]
    right_by_step = {p["step_index"]: p for p in right}
    return adopt_modifications(diff_steps, right_by_step=right_by_step)


# ---- 映射规则 ----
def test_adopt_input_leaf_diff():
    """输入区叶子差异 → input_context.<path> 修改(值取右侧)。"""
    a = _pt(0, {"content": "OUT"}, {"messages": [{"role": "user", "content": "hi"}], "model": "fake"})
    b = _pt(0, {"content": "OUT"}, {"messages": [{"role": "user", "content": "INJECTED"}], "model": "fake"}, source="R")
    mods = adopt_modifications(_diff_steps([a], [b]))
    assert mods == [
        Modification(
            step=0,
            field="input_context.messages[0].content",
            value="INJECTED",
        )
    ]


def test_adopt_output_diff_whole_override():
    """输出差异 → 整段 output 覆盖,不真调。"""
    a = _pt(0, {"content": "a"})
    b = _pt(0, {"content": "X"}, source="R")
    mods = _adopt([a], [b])
    assert mods == [Modification(step=0, field="output", value={"content": "X"})]


def test_adopt_output_child_diff_collapses_to_whole():
    """output 子路径差异 → 合并为整段 output 覆盖(避免子路径拼接歧义)。"""
    a = _pt(0, {"content": "a", "extra": 1})
    b = _pt(0, {"content": "X", "extra": 1}, source="R")
    mods = _adopt([a], [b])
    # 只有 output.content 一处变化 → 一条整段覆盖
    assert len(mods) == 1
    assert mods[0].field == "output"
    assert mods[0].value == {"content": "X", "extra": 1}


def test_adopt_list_index_path():
    """列表索引差异保留路径(messages[0].content)。"""
    a = _pt(0, {"content": "OUT"}, {"messages": [{"role": "user", "content": "hi"}], "model": "fake"})
    b = _pt(0, {"content": "OUT"}, {"messages": [{"role": "user", "content": "bye"}], "model": "fake"}, source="R")
    mods = adopt_modifications(_diff_steps([a], [b]))
    assert mods[0].field == "input_context.messages[0].content"
    assert mods[0].value == "bye"


def test_adopt_removed_skipped():
    """removed(仅左侧有,右侧无值)→ 跳过,不生成采纳修改。"""
    a = _pt(0, {"content": "a", "extra": 1})
    b = _pt(0, {"content": "a"}, source="R")
    mods = adopt_modifications(_diff_steps([a], [b]))
    # output.extra 为 removed → 跳过;无其他差异
    assert mods == []


def test_adopt_same_step_no_mods():
    """same 步骤不生成修改。"""
    a = _pt(0, {"content": "a"}, {"messages": [{"role": "user", "content": "hi"}]})
    b = _pt(0, {"content": "a"}, {"messages": [{"role": "user", "content": "hi"}]})
    mods = adopt_modifications(_diff_steps([a], [b]))
    assert mods == []


def test_adopt_only_side_no_mods():
    """only_left / only_right 步骤无另一侧值可采纳 → 不生成。"""
    left = [_pt(0, {"content": "a"}), _pt(1, {"content": "b"})]
    right = [_pt(0, {"content": "a"}, source="R")]
    mods = adopt_modifications(_diff_steps(left, right))
    assert mods == []
    mods2 = adopt_modifications(_diff_steps(right, left))
    assert mods2 == []


def test_adopt_multiple_steps_sorted():
    """多步骤:排序稳定(按 step,同步骤输出覆盖在前)。"""
    a0 = _pt(0, {"content": "a"}, {"messages": [{"role": "user", "content": "hi"}]})
    b0 = _pt(0, {"content": "X"}, {"messages": [{"role": "user", "content": "INJECT"}]}, source="R")
    a1 = _pt(1, {"content": "b"})
    b1 = _pt(1, {"content": "Y"}, source="R")
    mods = _adopt([a0, a1], [b0, b1])
    assert [(m.step, m.field) for m in mods] == [
        (0, "output"),
        (0, "input_context.messages[0].content"),
        (1, "output"),
    ]
    assert mods[1].value == "INJECT"
    assert mods[2].value == {"content": "Y"}


# ---- preview_adopt:只读语义 ----
def test_preview_adopt_read_only(env):
    """preview 只返回修改列表,不创建分支(分支集合不变)。"""
    from agent_inspect._context import MODE_FORK, ExecutionCursor, reset_cursor, set_cursor
    from tests.conftest import FakeLLM, run_agent

    llm = FakeLLM(["a", "b", "c"])
    run_agent(env.interceptor, 3, llm)
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]

    branch, _ = env.fork.request_fork(
        trace_id=trace.id, from_branch=root.id, from_step=1
    )
    cursor = ExecutionCursor(
        trace_id=trace.id,
        branch_id=branch.id,
        mode=MODE_FORK,
        replay_branch_id=root.id,
        branch_from_step=1,
        dry_run=False,
    )
    token = set_cursor(cursor)
    try:
        run_agent(env.interceptor, 3, FakeLLM(["X", "Y"]))
    finally:
        reset_cursor(token)

    before = len(env.store.list_branches(trace.id))
    result = preview_adopt(
        env.store,
        env.recorder.serializer,
        env.recorder.context_snap,
        root.id,  # branch_a:主分支(记录分支)
        branch.id,  # branch_b:对比分支(fork 分支)
        from_step=1,
    )
    after = len(env.store.list_branches(trace.id))
    assert before == after  # 只读,未创建分支
    assert result["dry_run"] is True
    assert result["branch_a"] == root.id
    assert result["branch_b"] == branch.id
    assert result["from_step"] == 1
    # step1 输出 a vs X → 一条 output 覆盖修改
    assert any(
        m["step"] == 1 and m["field"] == "output" and m["value"] == {"content": "X"}
        for m in result["modifications"]
    )


def test_preview_adopt_filtered_steps(env):
    """steps 过滤:只采纳指定步骤的差异。"""
    from agent_inspect._context import MODE_FORK, ExecutionCursor, reset_cursor, set_cursor
    from tests.conftest import FakeLLM, run_agent

    run_agent(env.interceptor, 3, FakeLLM(["a", "b", "c"]))
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]

    branch, _ = env.fork.request_fork(
        trace_id=trace.id, from_branch=root.id, from_step=1
    )
    cursor = ExecutionCursor(
        trace_id=trace.id,
        branch_id=branch.id,
        mode=MODE_FORK,
        replay_branch_id=root.id,
        branch_from_step=1,
        dry_run=False,
    )
    token = set_cursor(cursor)
    try:
        run_agent(env.interceptor, 3, FakeLLM(["X", "Y"]))
    finally:
        reset_cursor(token)

    result = preview_adopt(
        env.store,
        env.recorder.serializer,
        env.recorder.context_snap,
        root.id,
        branch.id,
        from_step=1,
        steps=[1],
    )
    steps = {m["step"] for m in result["modifications"]}
    assert steps == {1}  # step2(Y vs c)未被采纳