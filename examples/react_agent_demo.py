"""一行起一个 LangChain ReAct agent 的 Agent-Inspect 演示。

    python examples/react_agent_demo.py

流程(自动完成,无需任何 API key,可离线演示):
1. `agent_inspect.start()` 一行启用拦截 + 内嵌面板 + 自动开浏览器;
2. 跑一个真实 LangChain ReAct agent(思考 → 工具调用 add → 作答),记录为一条 trace;
3. 从首个决策点 fork,把 prompt 改成另一道加法题;
4. 执行 fork 分支(前缀回放 + 后缀真实执行),得到按新 prompt 演化的分支;
5. 面板里并排对照「记录分支」与「fork 分支」。

内置 `ScriptedChatModel`:按脚本逐次返回确定性回复,替代真实 LLM,
使演示可离线重复运行;换用 `ChatOpenAI(...)` 即可接真实模型。
"""
from __future__ import annotations

import time

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import PrivateAttr

import agent_inspect
from agent_inspect.fork import Modification


@tool
def add(x: int, y: int) -> int:
    """把两个整数相加。"""
    return x + y


class ScriptedChatModel(BaseChatModel):
    """确定性脚本化 chat model:按脚本逐次返回,替代真实 LLM 便于离线演示。"""

    _script: list = PrivateAttr(default_factory=list)
    _i: int = PrivateAttr(default=0)
    _seen: list = PrivateAttr(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append([getattr(m, "content", None) for m in messages])
        msg = self._script[self._i]
        self._i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


def make_react_agent(script):
    """新建一个绑定脚本化 model 的 LangChain ReAct agent(带 add 工具)。

    返回 (graph, model):model 供校验调用次数/实际收到的 prompt。
    """
    model = ScriptedChatModel()
    model._script = list(script)
    model._i = 0
    return create_agent(model, tools=[add]), model


def run(session) -> None:
    # 1) 记录一条 ReAct 执行:一次工具调用(add 1+2)后作答
    graph, _ = make_react_agent(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="1 + 2 = 3"),
        ]
    )
    with session.trace() as tid:
        out = graph.invoke({"messages": [{"role": "user", "content": "1 + 2 等于多少?"}]})
    print(f"[demo] 已记录 trace {tid};最终答案: {out['messages'][-1].content}")

    # 2) 从 step1(tool 调用)fork,把 add 参数改成 4+5 → 分支按新参数真实执行
    root = session.store.get_trace(tid).root_branch_id
    branch, plan = session.fork.request_fork(
        trace_id=tid,
        from_branch=root,
        from_step=1,
        modifications=[
            Modification(step=1, field="input_context.x", value=4),
            Modification(step=1, field="input_context.y", value=5),
        ],
        note="演示:从 step1 改 add 参数为 4+5",
    )
    print(f"[demo] 已创建 fork 分支 {branch.id}(起点 step={plan.branch_from_step})")

    graph2, _ = make_react_agent(
        [
            # step0 由前缀回放提供 tool_call;这里只准备 step2(LLM 最终回答)的回复
            AIMessage(content="4 + 5 = 9"),
        ]
    )
    with session.trace():
        out2 = graph2.invoke({"messages": [{"role": "user", "content": "1 + 2 等于多少?"}]})
    print(f"[demo] fork 分支最终答案: {out2['messages'][-1].content}")


def main() -> None:
    session = agent_inspect.start()  # 一行启用:拦截 + 记录 + 内嵌面板 + 自动开浏览器
    print(f"[demo] 面板地址: {session.url}")
    try:
        run(session)
        print(f"[demo] 打开面板 {session.url},即可看到「记录分支」与「fork 分支」并排对照")
        print("[demo] 按 Ctrl+C 退出")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()
