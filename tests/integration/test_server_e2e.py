"""端到端集成测试:内嵌服务 + 决策点 + Fork + 生命周期(走真实 HTTP/SSE)。

对应 spec `local-runtime`(一次调用/内嵌服务/实时/零外置后端/生命周期)与
`trace-ui`(终态呈现)。不依赖第三方客户端库,用标准库 urllib 打本机端口。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.request
from pathlib import Path

import pytest

from agent_inspect.session import Session

from tests.conftest import FakeLLM, run_agent


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _post(base: str, path: str, payload: dict):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        return e.code, body


def _traces(base: str):
    _st, body = _get(base, "/api/traces")
    return body


@pytest.fixture
def session(tmp_path):
    s = Session(db_path=str(tmp_path / "e2e.db"), autostart_browser=False)
    yield s
    s.stop()


def test_record_fork_lifecycle_e2e(session):
    """一次会话内:记录 → 标记完成 → Fork 创建 → Fork 后缀真调回流 → 终态可查。

    覆盖 spec:local-runtime(一次调用/内嵌服务/进程内自托管/无外置后端)、
    fork(面板发起 Fork / 修改在提交后生效)、trace-ui(实时回流 / 终态呈现)。
    """
    base = session.url

    # ---- 1) 记录一条 trace ----
    with session.trace() as tid:
        llm = FakeLLM(["a", "b", "c"])
        assert run_agent(session.interceptor, 3, llm) == ["a", "b", "c"]
        assert llm.calls == 3  # 记录态:全真调

    # 生命周期:作用域退出后标记完成
    traces = _traces(base)
    t = next(t for t in traces if t["id"] == tid)
    assert t["lifecycle"] == "done"

    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]
    assert root
    _st, points = _get(base, f"/api/branches/{root}/points")
    assert [(p["step_index"], p["output"]["content"]) for p in points] == [
        (0, "a"),
        (1, "b"),
        (2, "c"),
    ]

    # ---- 2) 面板发起 Fork:from_step=2,注入 step2 输出 ----
    st, res = _post(
        base,
        "/api/forks",
        {
            "trace_id": tid,
            "branch_id": root,
            "from_step": 2,
            "modifications": [
                {"step": 2, "field": "output", "value": "FORKED"}
            ],
            "note": "e2e fork",
        },
    )
    assert st == 200, res
    fork_branch = res["branch"]
    assert fork_branch["origin"] == "fork"
    assert fork_branch["branch_from_step"] == 2

    # ---- 3) 执行 Fork 分支:前缀回放(不真调),后缀真调 + 注入 ----
    with session.trace():
        llm2 = FakeLLM(["x"])  # step2 注入 output → 不真调;step0/1 前缀回放
        outs = run_agent(session.interceptor, 3, llm2)
    assert outs == ["a", "b", "FORKED"]  # 前缀回放 a,b;step2 注入 FORKED
    assert llm2.calls == 0  # 注入 output 不真调(spec 注入修改.修改工具返回)

    # 新分支决策点可经 API 读取(实时回流的基础:UI 轮询/SSE 追加)
    _st, fpts = _get(base, f"/api/branches/{fork_branch['id']}/points")
    assert [p["output"]["content"] for p in fpts] == ["FORKED"]
    assert all(p["step_index"] == 2 for p in fpts)

    # ---- 4) 分支图:两条分支均可枚举 ----
    _st, data = _get(base, f"/api/traces/{tid}")
    assert {b["origin"] for b in data["branches"]} == {"record", "fork"}


def test_aborted_lifecycle(session):
    """异常退出标记 aborted,已登记决策点保留(spec 异常中止标记)。"""
    base = session.url
    with pytest.raises(RuntimeError):
        with session.trace() as tid:
            run_agent(session.interceptor, 1, FakeLLM(["a"]))
            raise RuntimeError("boom")
    traces = _traces(base)
    t = next(t for t in traces if t["id"] == tid)
    assert t["lifecycle"] == "aborted"
    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]
    _st, pts = _get(base, f"/api/branches/{root}/points")
    assert len(pts) == 1  # 中止前已登记者不丢


def test_lifecycle_rest_endpoint(session):
    """生命周期 REST 可显式标记终态(spec 查询带生命周期筛选)。"""
    base = session.url
    with session.trace() as tid:
        run_agent(session.interceptor, 1, FakeLLM(["a"]))
    st, res = _post(base, f"/api/traces/{tid}/lifecycle", {"lifecycle": "done"})
    assert st == 200 and res["lifecycle"] == "done"
    st, res = _post(base, f"/api/traces/{tid}/lifecycle", {"lifecycle": "bogus"})
    assert st == 422
    st, res = _post(base, "/api/traces/does-not-exist/lifecycle", {"lifecycle": "done"})
    assert st == 404
    # 按生命周期筛选
    done = _traces(base)
    assert all(t["lifecycle"] == "done" for t in done)


def test_sse_stream_established(session):
    """SSE 实时流可建立(text/event-stream)(spec 实时双向消息)。"""
    sock = socket.create_connection(("127.0.0.1", session.port), timeout=5)
    sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: x\r\n\r\n")
    sock.settimeout(3)
    try:
        head = sock.recv(4096)
    except socket.timeout:
        head = b""
    sock.close()
    assert b"200 OK" in head and b"text/event-stream" in head


def test_ui_built_spa_served():
    """构建产物存在时 `/` 以 React 单页托管(spec 本机内嵌服务)。"""
    ui = Path(__file__).resolve().parents[2] / "web" / "dist"
    if not (ui / "index.html").is_file():
        pytest.skip("web/dist 未构建(npm run build 后再跑)")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        s = Session(db_path=str(Path(tmp) / "ui.db"), autostart_browser=False, ui_dir=str(ui))
        try:
            with urllib.request.urlopen(s.url + "/", timeout=5) as r:
                body = r.read().decode("utf-8")
            assert r.status == 200 and "Agent-Inspect" in body
            assert "/assets/" in body  # Vite 打包产物引用
        finally:
            s.stop()
