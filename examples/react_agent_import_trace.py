"""导入外部链路并 Fork 演示:吃「别人录好的 trace」,在导入链路上做反事实实验。

    python examples/react_agent_import_trace.py

流程(自动完成,无需任何 API key,可离线演示):
1. `agent_inspect.start()` 一行启用拦截 + 内嵌面板 + 自动开浏览器;
2. 记录一段真实 LangChain ReAct agent 执行(思考 → add 工具 → 作答);
3. 把这段执行合成为 span 导出 JSON 并落盘为 `imported_trace.json`
   (真实场景里,这份文件由观测平台/同事导出后交给你;此处从已记录
   trace 生成等价 JSON,让演示可离线重复);
4. 经 `POST /api/traces/import` 把该文件导入 → 面板出现带「导入」徽标的
   trace(与自录 trace 同构:可查看、可 Fork、可分支 diff);
5. 对导入 trace 的 add 工具调用步骤发起 Fork,把工具参数注入修改为 4+5
   ——前缀(LLM 决策点)用导入的输出确定性回放、不真调;
6. fork 后缀真实执行:add 按新参数真实计算,Agent 基于其结果作答,
   与原运行对照。
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

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
    _called: int = PrivateAttr(default=0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._called += 1
        msg = self._script[self._i]
        self._i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


def make_react_agent(script):
    """新建一个绑定脚本化 model 的 LangChain ReAct agent(带 add 工具)。"""
    model = ScriptedChatModel()
    model._script = list(script)
    model._i = 0
    return create_agent(model, tools=[add]), model


def export_span_json(session, trace_id: str, path: Path) -> Path:
    """把已记录 trace 反向合成为 span 导出 JSON(模拟外部观测工具的导出文件)。"""
    with urllib.request.urlopen(
        f"{session.url}/api/traces/{trace_id}", timeout=5
    ) as r:
        data = json.loads(r.read().decode("utf-8"))
    root = data["trace"]["root_branch_id"]
    with urllib.request.urlopen(
        f"{session.url}/api/branches/{root}/points", timeout=5
    ) as r:
        points = json.loads(r.read().decode("utf-8"))

    spans = []
    prev_id = None
    base_ms = 1720000000000
    for i, p in enumerate(points):
        sid = f"sp{i}"
        start = base_ms + i * 10
        attrs = {}
        if p["kind"] == "llm":
            messages = [
                {"message": {"role": m.get("role"), "content": m.get("content")}}
                for m in p["input_context"].get("messages", [])
            ]
            out_msgs = []
            if p["output"] is not None:
                out = {"message": {"role": "assistant", "content": p["output"].get("content")}}
                if p["output"].get("tool_calls"):
                    out["message"]["tool_calls"] = p["output"]["tool_calls"]
                out_msgs = [out]
            attrs = {
                "openinference.span.kind": "LLM",
                "llm.model_name": p["input_context"].get("model") or "unknown",
                "llm.input_messages": json.dumps(messages, ensure_ascii=False),
                "llm.output_messages": json.dumps(out_msgs, ensure_ascii=False),
            }
        else:
            attrs = {
                "openinference.span.kind": "TOOL",
                "tool.name": p["input_context"].get("tool"),
                "tool.parameters": json.dumps(p["input_context"].get("args"), ensure_ascii=False),
                "tool.return_value": json.dumps((p["output"] or {}).get("result"), ensure_ascii=False),
            }
        spans.append(
            {
                "span_id": sid,
                "parent_span_id": prev_id,
                "name": p["agent_id"],
                "start_time": start,
                "end_time": start + 5,
                "attributes": attrs,
            }
        )
        prev_id = sid

    payload = {"agent_name": "imported-from-export", "spans": spans}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def import_span_json(session, path: Path) -> dict:
    """经 POST /api/traces/import 导入 span 导出文件(与面板「导入」按钮同一契约)。"""
    req = urllib.request.Request(
        f"{session.url}/api/traces/import",
        data=path.read_bytes(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def run(session) -> None:
    # 1) 记录一段原始执行:1 + 2
    graph1, _ = make_react_agent(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"x": 1, "y": 2}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="1 + 2 = 3"),
        ]
    )
    with session.trace() as tid:
        out1 = graph1.invoke({"messages": [{"role": "user", "content": "1 + 2 等于多少?"}]})
    print(f"[demo] 原始运行: {out1['messages'][-1].content}")

    # 2) 合成 span 导出文件(模拟外部观测工具导出)→ 导入
    export_path = Path("imported_trace.json")
    export_span_json(session, tid, export_path)
    res = import_span_json(session, export_path)
    imported_tid = res["trace_id"]
    print(
        f"[demo] 已导入 {export_path} → trace {imported_tid}"
        f"(决策点 ×{res['decision_points']},忽略 span ×{res['skipped']};面板带「导入」徽标)"
    )

    # 3) 对导入链路的 add 工具步骤发起 Fork,把参数注入修改为 4+5(工具真实重跑)
    _st, data = session_store_get(session, imported_tid)
    root = data["trace"]["root_branch_id"]
    points = data_pts(session, root)
    tool_step = next(p["step_index"] for p in points if p["kind"] == "tool")
    branch, plan = session.fork.request_fork(
        trace_id=imported_tid,
        from_branch=root,
        from_step=tool_step,
        modifications=[
            Modification(step=tool_step, field="input_context.args.x", value=4),
            Modification(step=tool_step, field="input_context.args.y", value=5),
        ],
        note="import-fork demo: add 参数改为 4+5",
    )
    print(f"[demo] 已在导入 trace 的 step{tool_step}(add 工具)创建 fork 分支 {branch.id}")

    # 4) 执行 fork:step0(思考)回放导入输出、step1 工具按新参数真实计算、step2 真调作答
    graph2, model2 = make_react_agent([AIMessage(content="4 + 5 = 9(参数被注入修改)")])
    with session.trace():
        out2 = graph2.invoke({"messages": [{"role": "user", "content": "1 + 2 等于多少?"}]})
    print(f"[demo] fork 分支最终答案: {out2['messages'][-1].content}")
    print(f"[demo] 真实 LLM 调用次数: {model2._called}(前缀思考步回放自导入输出,不真调)")


def session_store_get(session, trace_id: str) -> tuple:
    with urllib.request.urlopen(f"{session.url}/api/traces/{trace_id}", timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def data_pts(session, branch_id: str) -> list:
    with urllib.request.urlopen(
        f"{session.url}/api/branches/{branch_id}/points", timeout=5
    ) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    session = agent_inspect.start()  # 一行启用:拦截 + 记录 + 内嵌面板 + 自动开浏览器
    print(f"[demo] 面板地址: {session.url}")
    try:
        run(session)
        print(
            f"[demo] 打开面板 {session.url}:带「导入」徽标的 trace 即导入链路,"
            "其 fork 分支与原链路可并排对照"
        )
        print("[demo] 按 Ctrl+C 退出")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()
