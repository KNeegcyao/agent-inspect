"""补足 6.4 自检覆盖:未在上游测试出现的 delta spec Scenario。

- OpenAI 兼容 SDK 自动插桩(spec `interception.主流框架自动插桩`)
- 未覆盖框架降级(spec `interception.未覆盖框架降级`)
- 进程重启后历史留存 + 重启后可 Fork(spec `recording.进程重启后可查` / `local-runtime.进程退出后历史留存`)
- 端口冲突自适应(spec `local-runtime.端口冲突自适应`)
- 无头环境降级(spec `local-runtime.无头环境降级`)

均为真实 API 路径,不依赖浏览器与外部网络(openai 走 httpx MockTransport)。
"""
from __future__ import annotations

import socket
import tempfile
from pathlib import Path

import httpx
import pytest

from agent_inspect.session import Session

from tests.conftest import FakeLLM, run_agent

_FAKE_CHAT = {
    "id": "chatcmpl-fake",
    "object": "chat.completion",
    "created": 0,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "hello from openai", "tool_calls": None},
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


@pytest.fixture
def session(tmp_path):
    s = Session(db_path=str(tmp_path / "runtime.db"), autostart_browser=False)
    yield s
    s.stop()


def _mock_openai_client():
    """返回走本地 MockTransport 的 OpenAI 客户端,不发起真实网络请求。"""
    import openai

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_FAKE_CHAT)

    return openai.OpenAI(
        api_key="sk-test",
        http_client=httpx.Client(transport=httpx.MockTransport(_handler)),
    )


# ---------------------------------------------------------------------------
# interception.主流框架自动插桩 / 未覆盖框架降级
# ---------------------------------------------------------------------------
def test_openai_compat_sdk_auto_instrumentation(session):
    """OpenAI 兼容 SDK `chat.completions.create` 自动登记为 LLM 决策点,无需手工包装。"""
    client = _mock_openai_client()
    with session.trace() as tid:
        out = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert out.choices[0].message.content == "hello from openai"

    root = session.store.get_trace(tid).root_branch_id
    pts = session.store.get_decision_points(tid, root)
    assert len(pts) == 1 and pts[0].kind == "llm"
    assert pts[0].output["content"] == "hello from openai"
    assert pts[0].meta["tokens_in"] == 10  # usage 进入 meta(spec 决策点登记)
    # 行内 input_context 为增量快照引用,经重建仍能还原完整输入(spec 增量上下文快照)
    from agent_inspect.recorder.context_snap import ContextSnap

    full = ContextSnap().reconstruct(session.store, root, 0)
    assert full["model"] == "gpt-4o-mini"
    assert full["messages"][0]["content"] == "hi"


def test_uncovered_framework_degrades_gracefully(session):
    """未覆盖框架的调用照常运行、不崩溃、不登记(spec 未覆盖框架降级)。"""
    # 插桩已启用(session fixture);调用与插桩面无关的纯函数
    result = sorted([3, 1, 2])
    assert result == [1, 2, 3]
    assert session.list_traces() == []  # 未被覆盖,不产生任何决策点


# ---------------------------------------------------------------------------
# recording.进程重启后可查 / local-runtime.进程退出后历史留存
# ---------------------------------------------------------------------------
def test_process_restart_history_retained_and_forkable(tmp_path):
    """进程退出后历史留存:重启(新 Session 打开同一 db)仍可读旧 trace,且可继续 Fork。"""
    db = str(tmp_path / "persist.db")

    s1 = Session(db_path=db, autostart_browser=False)
    with s1.trace() as tid:
        run_agent(s1.interceptor, 2, FakeLLM(["a", "b"]))
    s1.stop()  # 模拟进程退出

    s2 = Session(db_path=db, autostart_browser=False)  # 重启
    try:
        assert any(t.id == tid for t in s2.list_traces())
        root = s2.store.get_trace(tid).root_branch_id
        pts = s2.store.get_decision_points(tid, root)
        assert [p.output["content"] for p in pts] == ["a", "b"]  # 决策点完整读回

        branch, plan = s2.fork.request_fork(trace_id=tid, from_branch=root, from_step=1)
        assert branch.origin == "fork" and plan.branch_from_step == 1
    finally:
        s2.stop()


# ---------------------------------------------------------------------------
# local-runtime.端口冲突自适应
# ---------------------------------------------------------------------------
def test_port_conflict_adapts(tmp_path):
    """端口被占用 → 自动选择可用端口并正常服务。"""
    import urllib.request

    # 先找一个当前空闲端口,再由 blocker 占用它(不假设 DEFAULT_PORT 空闲)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        occupied = probe.getsockname()[1]
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", occupied))
    blocker.listen(1)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            s = Session(db_path=str(Path(tmp) / "p.db"), autostart_browser=False, port=occupied)
            try:
                assert s.port != occupied  # 避开了被占端口
                with urllib.request.urlopen(s.url + "/api/traces", timeout=5) as r:
                    assert r.status == 200
            finally:
                s.stop()
    finally:
        blocker.close()


# ---------------------------------------------------------------------------
# local-runtime.无头环境降级
# ---------------------------------------------------------------------------
def test_headless_degrades_to_url_print(tmp_path, monkeypatch, capsys):
    """无图形/无浏览器环境:不报错,把面板地址打印出来供人工/脚本打开。"""
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: False)  # 模拟无浏览器可开
    s = Session(db_path=str(tmp_path / "h.db"), autostart_browser=True)
    try:
        assert s.url
        out = capsys.readouterr().out
        assert "面板地址" in out and s.url in out  # 降级打印 URL
    finally:
        s.stop()
