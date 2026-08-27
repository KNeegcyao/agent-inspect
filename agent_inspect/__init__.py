"""Agent-Inspect:LLM Agent 的交互式逐步调试器。

拦截(record/replay/fork 三态)、增量录制、反事实 Fork,一行启用:
    import agent_inspect
    session = agent_inspect.start()
    # ... 运行你的 Agent(经 LangChain/OpenAI SDK)...
    session.stop()
"""
from .session import DEFAULT_DB, DEFAULT_PORT, Session, start

__all__ = ["Session", "start", "DEFAULT_DB", "DEFAULT_PORT"]
__version__ = "0.1.0"
