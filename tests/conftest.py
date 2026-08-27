"""共享测试设施:FakeLLM(免 token)、store/env fixture、模式运行辅助。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_inspect._server.store.queries import Store
from agent_inspect.fork import ForkController
from agent_inspect.interceptor.base import Interceptor
from agent_inspect.recorder import Recorder


class FakeLLM:
    """确定性的伪 LLM:按脚本逐次返回;记录调用次数以断言真调/回放。"""

    def __init__(self, scripted: list) -> None:
        self._responses = list(scripted)
        self._i = 0
        self.calls = 0

    def call(self, *a, **kw):
        self.calls += 1
        if self._i >= len(self._responses):
            return None
        r = self._responses[self._i]
        self._i += 1
        return r


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(str(tmp_path / "test.db"))
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _clean_cursor():
    """每个测试前清空 contextvars 游标,避免跨测试污染(进程级 contextvar)。"""
    from agent_inspect._context import reset_cursor, set_cursor

    token = set_cursor(None)
    yield
    reset_cursor(token)


@pytest.fixture
def env(store) -> SimpleNamespace:
    """无服务的最小运行环境:store + recorder + interceptor + fork。"""
    rec = Recorder(store, on_event=None)
    fork = ForkController(store)
    interceptor = Interceptor(rec, controller=fork)
    return SimpleNamespace(store=store, recorder=rec, fork=fork, interceptor=interceptor)


def run_agent(interceptor: Interceptor, n_steps: int, llm: FakeLLM, kind: str = "llm"):
    """顺序执行 n 个 LLM 决策点,返回各步 native 输出。

    reconstruct 与 shape_output 互逆:shape_output 包装为 {"content": x},
    reconstruct 从存储形态还原出 native 值 x(dry_run 时返回 None)。
    """
    outs = []
    for _ in range(n_steps):
        outs.append(
            interceptor.sroute(
                kind=kind,
                agent_id="fake-llm",
                input_context={"messages": [{"role": "user", "content": "hi"}], "model": "fake"},
                call=lambda: llm.call(),
                reconstruct=lambda d: d["content"] if d else None,
                shape_output=lambda x: {"content": x},
            )
        )
    return outs
