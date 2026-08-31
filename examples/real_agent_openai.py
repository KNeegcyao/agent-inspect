"""真实 LLM Agent 接入演示:一条命令接入你已有的 OpenAI 兼容 Agent(真实调用)。

    python examples/real_agent_openai.py

这是与 demo(ScriptedChatModel)的本质区别:这里的每次 LLM 调用都是**真实 HTTP 调用**
(真实 token、真实流式、真实耗时),agent_inspect 一样全自动拦截——因为插桩挂在
openai SDK 的高语义稳定入口上,与"背后是不是真模型"无关。

前置(三选一,均通过环境变量):
1. OpenAI 官方:      set OPENAI_API_KEY=sk-...
2. 任意兼容端点:      set OPENAI_API_KEY=sk-...  &  set OPENAI_BASE_URL=https://api.deepseek.com/v1
                     &  set DEMO_MODEL=deepseek-chat        (DeepSeek/Moonshot/one-api/vLLM...)
3. 本地 Ollama(免 key):
                     ollama pull qwen2.5:0.5b
                     set OPENAI_BASE_URL=http://127.0.0.1:11434/v1  &  set DEMO_MODEL=qwen2.5:0.5b

流程:agent_inspect.start() 一行启用 → 真实流式 + 真实工具调用的 ReAct 循环
→ 面板实时看到每次真实调用(完整 prompt/输出/耗时/token)→ 可在面板发起 Fork
反事实实验。接入你已有的 Agent 只需同样两行:import + start(),业务代码零改动。
"""
from __future__ import annotations

import json
import os
import sys
import time


def _require_env() -> tuple[str, str, str]:
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("DEMO_MODEL", "gpt-4o-mini")
    if not api_key and not (base_url and "11434" in base_url):
        # Ollama 免 key;其余端点需要 key
        print("[real] 缺少 OPENAI_API_KEY。三种配置方式见文件头注释;", file=sys.stderr)
        print('[real] 例: set OPENAI_API_KEY=sk-... 或 Ollama: set OPENAI_BASE_URL=http://127.0.0.1:11434/v1', file=sys.stderr)
        sys.exit(2)
    return api_key or "ollama", base_url or "", model


def main() -> None:
    api_key, base_url, model = _require_env()

    import openai
    from openai import OpenAI

    import agent_inspect

    session = agent_inspect.start()  # 一行启用:拦截 + 面板 + 自动开浏览器
    print(f"[real] 面板地址: {session.url}")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url or None,
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "add",
                "description": "把两个整数相加",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
        }
    ]

    def add(a: int, b: int) -> int:
        return a + b

    def run_turn(question: str) -> str:
        """真实 ReAct 循环:流式调用 + 工具执行,直到最终回答。"""
        messages: list[dict] = [{"role": "user", "content": question}]
        for _ in range(5):  # 防失控上限
            stream = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                stream=True,
            )
            content_parts: list[str] = []
            tool_calls: dict[int, dict] = {}
            for chunk in stream:  # 真实流式:chunk 原样消费;插桩旁路累积并登记
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                    print(delta.content, end="", flush=True)
                for tc in delta.tool_calls or []:
                    slot = tool_calls.setdefault(tc.index, {"id": tc.id, "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
            print()

            if not tool_calls:
                return "".join(content_parts)

            messages.append(
                {"role": "assistant", "content": "".join(content_parts) or None,
                 "tool_calls": [
                     {"id": s["id"], "type": "function",
                      "function": {"name": s["name"], "arguments": s["args"]}}
                     for s in tool_calls.values()]
                 }
            )
            for s in tool_calls.values():
                result = add(**json.loads(s["args"]))  # 真实工具执行
                print(f"[real] 工具 {s['name']}({s['args']}) = {result}")
                messages.append({"role": "tool", "tool_call_id": s["id"], "content": str(result)})
        return "(达到轮次上限)"

    try:
        t0 = time.time()
        answer = run_turn("3 + 5 等于多少?算完后用一句话总结。")
        print(f"[real] 最终回答: {answer}  (耗时 {time.time() - t0:.1f}s)")
        print(f"[real] 打开面板 {session.url}:每次真实 LLM 调用与工具执行都已登记,")
        print("[real] 可查看完整 prompt/输出/耗时/token,并从任意决策点发起 Fork 反事实实验。")
        print("[real] 按 Ctrl+C 退出")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


if __name__ == "__main__":
    main()
