"""跨 trace 对比演示:两次独立运行(不同 prompt),在面板按 trace 分组对比分支。

    python examples/react_agent_compare_traces.py

流程(自动完成,无需任何 API key,可离线演示):
1. `agent_inspect.start()` 一行启用拦截 + 内嵌面板 + 自动开浏览器;
2. 记录两条真实 LangChain ReAct agent 的执行(思考 → 工具调用 add → 作答),
   一条问「1 + 2」,另一条问「4 + 5」→ 两个独立 trace;
3. 面板「对比分支」下拉按 trace 分组,可从另一条 trace 挑分支跨运行并排对照
   (spec compare-traces:跨 trace 分支 diff + 来源标注)。

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
    # 记录第一条 trace:1 + 2
    graph1, _ = make_react_agent(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="1 + 2 = 3"),
        ]
    )
    with session.trace() as tid1:
        out1 = graph1.invoke({"messages": [{"role": "user", "content": "1 + 2 等于多少?"}]})
    print(f"[demo] 已记录 trace {tid1}: {out1['messages'][-1].content}")

    # 记录第二条 trace:4 + 5(不同 prompt → 跨 trace 对比)
    graph2, _ = make_react_agent(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"x": 4, "y": 5}, "id": "c2", "type": "tool_call"}],
            ),
            AIMessage(content="4 + 5 = 9"),
        ]
    )
    with session.trace() as tid2:
        out2 = graph2.invoke({"messages": [{"role": "user", "content": "4 + 5 等于多少?"}]})
    print(f"[demo] 已记录 trace {tid2}: {out2['messages'][-1].content}")
    print(f"[demo] 两条 trace 就绪,可在面板「对比分支」跨 trace 分组对照")


def main() -> None:
    session = agent_inspect.start()  # 一行启用:拦截 + 记录 + 内嵌面板 + 自动开浏览器
    print(f"[demo] 面板地址: {session.url}")
    try:
        run(session)
        print(f"[demo] 打开面板 {session.url},在「对比分支」下拉按 trace 分组,挑另一条 trace 的分支跨运行并排对照")
        print("[demo] 按 Ctrl+C 退出")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()