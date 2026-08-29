"""跨进程追踪演示:父进程记录一段,派生带 env 的子进程记录另一段,子 trace 挂到父 trace 下。

    python examples/react_agent_cross_process.py

流程(自动完成,无需任何 API key,可离线演示):
1. 父进程 `agent_inspect.start()` 一行启用(临时 DB),记录一条 LangChain ReAct agent 执行 → trace P;
2. 父进程以 `AGENT_INSPECT_PARENT_TRACE=P` 环境变量派生子进程(同一 DB 文件),
   子进程记录另一条执行 → trace C(落库时 parent_trace_id=P);
3. 面板 trace 列表里 C 缩进显示并带「跨进程」徽标;打开 P 详情可看到「子 trace × 1」,
   打开 C 详情可看到「父 trace · P」并可点击跳转。

内置 `ScriptedChatModel` 确定性回复,换用 `ChatOpenAI(...)` 即可接真实模型。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import PrivateAttr

import agent_inspect

_CHILD_FLAG = "AGENT_INSPECT_CHILD_RUN"
_DB_ENV = "AGENT_INSPECT_DB"


@tool
def add(x: int, y: int) -> int:
    """把两个整数相加。"""
    return x + y


class ScriptedChatModel(BaseChatModel):
    """确定性脚本化 chat model:按脚本逐次返回,替代真实 LLM 便于离线演示。"""

    _script: list = PrivateAttr(default_factory=list)
    _i: int = PrivateAttr(default=0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self._script[self._i]
        self._i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


def run_agent(session, question: str, script: list) -> tuple[str, str]:
    """新建一个绑定脚本化 model 的 ReAct agent 并在 session.trace() 里跑一段。"""
    model = ScriptedChatModel()
    model._script = list(script)
    model._i = 0
    graph = create_agent(model, tools=[add])
    with session.trace() as tid:
        out = graph.invoke({"messages": [{"role": "user", "content": question}]})
    return tid, out["messages"][-1].content


def child_main() -> None:
    """子进程:同一 DB 文件,靠 env 声明父 trace,记录一条子 trace。"""
    db_path = os.environ[_DB_ENV]
    session = agent_inspect.start(db_path=db_path, autostart_browser=False)
    tid, ans = run_agent(
        session,
        "10 + 20 等于多少?",
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"x": 10, "y": 20}, "id": "c2", "type": "tool_call"}],
            ),
            AIMessage(content="10 + 20 = 30"),
        ],
    )
    print(f"[child] 已记录子 trace {tid}: {ans} (parent={os.environ.get('AGENT_INSPECT_PARENT_TRACE')})")
    session.stop()


def parent_main() -> None:
    """父进程:临时 DB,记录父 trace 后派生带 env 的子进程,并展示父子关联。"""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = tmp.name
    tmp.close()
    session = agent_inspect.start(db_path=db_path)
    print(f"[demo] 面板地址: {session.url}")
    try:
        tid, ans = run_agent(
            session,
            "1 + 2 等于多少?",
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}],
                ),
                AIMessage(content="1 + 2 = 3"),
            ],
        )
        print(f"[parent] 已记录父 trace {tid}: {ans}")

        # 派生带 env 的子进程:同一 DB 文件 + 声明父 trace
        env = {
            **os.environ,
            _DB_ENV: db_path,
            "AGENT_INSPECT_PARENT_TRACE": tid,
            _CHILD_FLAG: "1",
        }
        subprocess.run([sys.executable, __file__], env=env, check=True)

        # 从父 trace 侧确认子 trace 已挂载
        children = session.store.list_child_traces(tid)
        print(f"[parent] 父 trace {tid} 的子 trace × {len(children)}: {[c.id for c in children]}")
        print(f"[demo] 打开面板 {session.url},列表中子 trace 缩进并带「跨进程」徽标;父 trace 详情可见「子 trace × 1」")
        print("[demo] 按 Ctrl+C 退出")
        while True:
            import time

            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


def main() -> None:
    if os.environ.get(_CHILD_FLAG):
        child_main()
    else:
        parent_main()


if __name__ == "__main__":
    main()
