"""LangChain ReAct agent 端到端(对应 tasks 6.2/6.3)。

复用 `examples/react_agent_demo.py` 的脚本化 chat model 与 add 工具,
把演示流程固化为可断言测试(无需浏览器):

- 主流框架自动插桩:真实 LangChain `create_agent` 的每一步 LLM 调用与工具调用
  均被登记为决策点(spec `interception`);decision points 为 [llm, tool, llm]。
- 注入 prompt:从 step0 fork 改 prompt,分支首决策点真实收到修改后的 prompt
  (spec `fork.修改 prompt` / `fork.后缀真实执行`)。
- 关闭拦截零回归:stop() 卸载插桩后,同一 ReAct agent 按其原始路径照常运行
  (spec `interception.关闭零回归`)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_inspect.session import Session

# examples 非包,测试时把它加入导入路径以复用演示设施
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))
from react_agent_demo import (  # noqa: E402
    ScriptedChatModel,
    make_react_agent,
)
from agent_inspect.fork import Modification  # noqa: E402

REACT_SCRIPT = [
    AIMessage(
        content="",
        tool_calls=[{"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}],
    ),
    AIMessage(content="1 + 2 = 3"),
]
FORK_SCRIPT = [
    AIMessage(
        content="",
        tool_calls=[{"name": "add", "args": {"x": 4, "y": 5}, "id": "c2", "type": "tool_call"}],
    ),
    AIMessage(content="4 + 5 = 9"),
]


@pytest.fixture
def session(tmp_path):
    s = Session(db_path=str(tmp_path / "lc.db"), autostart_browser=False)
    yield s
    s.stop()


def _run(script, question):
    graph, model = make_react_agent(script)
    out = graph.invoke({"messages": [{"role": "user", "content": question}]})
    return model, out


def _branch_points(session, tid, branch_id):
    return session.store.get_decision_points(tid, branch_id)


def test_react_agent_auto_instrumentation(session):
    """真实 LangChain ReAct agent 自动插桩:llm+tool 决策点齐全(spec 主流框架自动插桩)。"""
    with session.trace() as tid:
        model, out = _run(REACT_SCRIPT, "1 + 2 等于多少?")
    assert out["messages"][-1].content == "1 + 2 = 3"
    assert model._i == 2  # 两次 LLM 调用

    root = session.store.get_trace(tid).root_branch_id
    pts = _branch_points(session, tid, root)
    assert [p.kind for p in pts] == ["llm", "tool", "llm"]  # 思考 → 工具 → 结果
    assert pts[0].output["tool_calls"][0]["name"] == "add"
    assert pts[0].output["tool_calls"][0]["args"] == {"x": 1, "y": 2}
    assert pts[1].output["result"]["name"] == "add"  # 工具返回
    assert pts[1].output["result"]["content"] == "3"
    assert pts[2].output["content"] == "1 + 2 = 3"


def test_fork_modify_prompt_react(session):
    """从 step0 fork 改 prompt:分支首决策点真实收到修改后的 prompt(spec fork.修改 prompt)。"""
    with session.trace() as tid:
        model, _ = _run(REACT_SCRIPT, "1 + 2 等于多少?")
    root = session.store.get_trace(tid).root_branch_id

    branch, plan = session.fork.request_fork(
        trace_id=tid,
        from_branch=root,
        from_step=0,
        modifications=[Modification(step=0, field="input_context.messages[0].content", value="4 + 5 等于多少?")],
        note="改 prompt",
    )
    assert plan.branch_from_step == 0

    with session.trace():
        model2, out2 = _run(FORK_SCRIPT, "1 + 2 等于多少?")
    # 分支最终答案按新 prompt 演化
    assert out2["messages"][-1].content == "4 + 5 = 9"
    # 首个决策点真实收到的 prompt 已被修改(非原 prompt)
    assert model2._seen[0][0] == "4 + 5 等于多少?"

    # 新分支决策点独立归属(spec fork.后缀决策点入分支 / 分支独立演化)
    fpts = _branch_points(session, tid, branch.id)
    assert [p.kind for p in fpts] == ["llm", "tool", "llm"]
    assert all(p.branch_id == branch.id for p in fpts)


def test_close_interception_zero_regression(tmp_path):
    """关闭拦截后 ReAct agent 原样运行(spec interception.关闭零回归)。"""
    # 先启用再关闭:验证 uninstall 后框架恢复原始路径
    s = Session(db_path=str(tmp_path / "off.db"), autostart_browser=False)
    s.stop()

    model, out = _run(REACT_SCRIPT, "1 + 2 等于多少?")
    assert out["messages"][-1].content == "1 + 2 = 3"
    assert model._i == 2  # 两次调用均真实执行(未被拦截吞掉)

    # 未启用拦截时,同样工作
    model2, out2 = _run(FORK_SCRIPT, "4 + 5 等于多少?")
    assert out2["messages"][-1].content == "4 + 5 = 9"


def test_scripted_model_is_pydantic_model():
    """演示用的脚本化 model 是合法 BaseChatModel(spec 主流框架自动插桩的承载物)。"""
    from langchain_core.language_models.chat_models import BaseChatModel

    model = ScriptedChatModel()
    assert isinstance(model, BaseChatModel)
    assert model._llm_type == "scripted"
