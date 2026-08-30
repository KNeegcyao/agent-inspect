"""决策点搜索测试(spec `trace-search`)。

覆盖:输入/输出命中、大小写不敏感、无命中空集、多分支排序、snippet 合成。
"""
from __future__ import annotations

from agent_inspect._context import reset_cursor, set_cursor
from agent_inspect.search import search_trace

from tests.conftest import FakeLLM, run_agent


def _seed_chain(env, step1_output: str):
    """两步链:每步输入含 hi(run_agent 固定输入)、输出 plan / 参数指定。"""
    llm = FakeLLM(["plan", step1_output])
    run_agent(env.interceptor, 2, llm)
    trace = env.store.list_traces()[0]
    return trace.id, trace.root_branch_id


def test_matches_input_and_output_case_insensitive(env):
    """输入与输出都参与匹配,大小写不敏感,标注命中来源(spec trace-search.匹配)。"""
    tid, _root = _seed_chain(env, "found THE Treasure")

    # 输入命中(每步输入均含 "hi",查询用大写)
    res = search_trace(env.store, env.recorder, tid, "HI")
    assert [(m["step_index"], m["matched_in"]) for m in res] == [(0, "input"), (1, "input")]

    # 输出命中(step1 输出含 treasure,大小写不同)
    res = search_trace(env.store, env.recorder, tid, "treasure")
    assert [(m["step_index"], m["matched_in"]) for m in res] == [(1, "output")]


def test_no_match_returns_empty(env):
    """无命中 → 空结果集(spec trace-search.无命中)。"""
    tid, _root = _seed_chain(env, "b")
    assert search_trace(env.store, env.recorder, tid, "never-present-string") == []


def test_results_ordered_by_branch_insertion_then_step(env):
    """多分支命中按分支插入序(根在前)、分支内步骤升序排序。"""
    llm = FakeLLM(["alpha", "beta"])
    run_agent(env.interceptor, 2, llm)
    trace = env.store.list_traces()[0]
    root = env.store.list_branches(trace.id)[0]

    # fork 分支:step0 回放根分支的 alpha(不再落盘),step1 真调含 alpha
    env.fork.request_fork(trace_id=trace.id, from_branch=root.id, from_step=1)
    token = set_cursor(None)
    try:
        run_agent(env.interceptor, 2, FakeLLM(["alpha"]))  # step0 回放不消耗脚本;step1 真调 → "alpha"
    finally:
        reset_cursor(token)

    res = search_trace(env.store, env.recorder, trace.id, "alpha")
    by_branch: dict[str, list[int]] = {}
    for m in res:
        by_branch.setdefault(m["branch_id"], []).append(m["step_index"])
    # 两个分支各命中一次;分支出现顺序遵循插入序(根在前)
    assert set(by_branch) == {root.id, res[-1]["branch_id"]}
    assert list(by_branch) == [root.id, res[-1]["branch_id"]]
    assert all(steps == sorted(steps) for steps in by_branch.values())
    assert all(m["matched_in"] == "output" for m in res)


def test_snippet_compacts_and_bounds(env):
    """snippet 压行且不超过命中前后半径的合理上界。"""
    long_text = "x" * 200 + "NEEDLE" + "y" * 200
    run_agent(env.interceptor, 1, FakeLLM([long_text]))
    trace = env.store.list_traces()[0]
    res = search_trace(env.store, env.recorder, trace.id, "needle")
    assert len(res) == 1
    snip = res[0]["snippet"]
    assert "needle" in snip
    assert "\n" not in snip and "  " not in snip
    assert len(snip) <= 2 * 60 + len("needle") + 2
