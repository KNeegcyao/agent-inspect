"""Agent-Inspect Live 活体调试(Mode C)演示。

    python examples/react_agent_live_debug.py

流程(自动完成,无需任何 API key,可离线演示):
1. `agent_inspect.start()` 一行启用拦截 + 内嵌面板 + 自动开浏览器;
2. 后台线程跑一个真实 LangChain ReAct agent(三次 LLM 决策点),模拟"运行中";
3. 主线程 attach 到运行中的 trace → 设断点(kind=llm);
4. 首个决策点命中断点暂停 → 检查输入;
5. step 单步 → 修改 step1 的 prompt → continue;
6. 移除断点后继续放行,agent 跑完;落盘可见 step1 输入已被替换。

内置 `ScriptedChatModel`:按脚本逐次返回确定性回复,替代真实 LLM,
使演示可离线重复运行;换用 `ChatOpenAI(...)` 即可接真实模型。
"""
from __future__ import annotations

import threading
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

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self._script[self._i]
        self._i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


def _wait_paused(gate, step: int, timeout: float = 5.0) -> dict:
    """轮询调试门状态直至目标步骤暂停。"""
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        state = gate.state()
        if state["paused_at"] == step:
            return state
        time.sleep(0.02)
    raise AssertionError(f"未在步骤 {step} 暂停,state={state}")


def run(session) -> None:
    holder: dict = {}
    start = threading.Event()
    done = threading.Event()

    def _agent_run():
        """后台线程:模拟一条运行中的 live trace(3 次 LLM 决策点)。"""
        try:
            model = ScriptedChatModel()
            model._script = [
                AIMessage(content="", tool_calls=[{"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}]),
                AIMessage(content="", tool_calls=[{"name": "add", "args": {"x": 3, "y": 4}, "id": "c2", "type": "tool_call"}]),
                AIMessage(content="1+2=3, 3+4=7"),
            ]
            graph = create_agent(model, tools=[add])
            with session.trace() as tid:
                holder["tid"] = tid
                start.wait(5)  # 等主线程 attach + 设断点再放行
                holder["outs"] = graph.invoke(
                    {"messages": [{"role": "user", "content": "请计算 1+2 与 3+4"}]}
                )["messages"][-1].content
        finally:
            done.set()

    th = threading.Thread(target=_agent_run, daemon=True)
    th.start()

    # 等 trace 建立(running)
    tid = None
    deadline = time.time() + 5
    while time.time() < deadline:
        tid = holder.get("tid")
        if tid:
            break
        time.sleep(0.02)
    assert tid is not None, "agent trace 未在预期时间内建立"
    print(f"[demo] 运行中 trace: {tid}")

    # ---- attach + 设断点(kind=llm)→ 放行 agent,首个决策点暂停 ----
    gate = session.debug.ensure_gate(tid)
    gate.attach()
    bp = gate.add_breakpoint(kind="llm")
    print(f"[demo] 已附加 + 设断点 {bp.kind} → 放行 agent")
    start.set()
    _wait_paused(gate, 0)
    print(f"[demo] 暂停于 step0:输入={gate.state() and _probe(gate)}")

    # ---- step 单步 → step1 ----
    gate.step()
    _wait_paused(gate, 1)
    print("[demo] step → 暂停于 step1")

    # ---- 修改 step1 的 prompt 并继续 ----
    gate.modify(
        step=1,
        field="input_context.messages[0].content",
        value="请只计算 1+2",
    )
    print("[demo] 修改 step1 输入(只算 1+2)→ continue")

    # ---- 移除断点后继续放行,agent 跑完 ----
    gate.remove_breakpoint(bp.id)
    gate.resume()
    assert done.wait(5), "agent 在 remove+continue 后未完成"
    print(f"[demo] agent 完成: {holder['outs']!r}")

    # ---- 落盘可见差异:step1 输入已被替换 ----
    root = session.store.get_trace(tid).root_branch_id
    pts = session.store.get_decision_points(tid, root)
    by_step = {p.step_index: p for p in pts}
    resolved = {
        s: session.recorder.serializer.resolve_dp(session.store, p, session.recorder.context_snap)
        for s, p in by_step.items()
    }
    print(f"[demo] step0 输入: {resolved[0]['input_context']['messages'][0]['content']!r}")
    print(f"[demo] step1 输入: {resolved[1]['input_context']['messages'][0]['content']!r}  ← 已替换")


def _probe(gate):
    """暂停时读一次完整输入(演示用途)。"""
    pp = getattr(gate, "paused_payload", None)
    if pp:
        return pp.get("input_context", {}).get("messages", [{}])[0].get("content")
    return None


def main() -> None:
    session = agent_inspect.start()  # 一行启用:拦截 + 记录 + 内嵌面板 + 自动开浏览器
    print(f"[demo] 面板地址: {session.url}")
    try:
        run(session)
        print(f"[demo] 打开面板 {session.url},查看 step1 输入已被替换的 live trace")
        print("[demo] 按 Ctrl+C 退出")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()
