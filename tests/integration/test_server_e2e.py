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


def _get_raw(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _post_raw(base: str, path: str, payload: dict):
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


def _delete_raw(base: str, path: str):
    req = urllib.request.Request(base + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        return e.code, body


def _retry_conn(fn):
    """Windows 全量负载下偶发的 10054(对端关闭空闲连接)重试一次。"""
    try:
        return fn()
    except ConnectionResetError:
        time.sleep(0.2)
        return fn()


# 全量负载下服务线程偶发回收空闲连接;读/写各重试一次,避免 10054 误报失败
def _get(base: str, path: str):
    return _retry_conn(lambda: _get_raw(base, path))


def _get_error(base: str, path: str):
    """GET 且期望非 2xx(404/422 等),返回 (status, json body)。"""
    req = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        return e.code, body


def _post(base: str, path: str, payload: dict):
    return _retry_conn(lambda: _post_raw(base, path, payload))


def _delete(base: str, path: str):
    return _retry_conn(lambda: _delete_raw(base, path))


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


def _delete(base: str, path: str):
    req = urllib.request.Request(base + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        return e.code, body


def _wait_debug_paused(base: str, tid: str, step: int, timeout: float = 15.0):
    """轮询调试状态直至目标步骤暂停(spec 指令实时送达执行侧)。"""
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        _st, state = _get(base, f"/api/debug/{tid}/state")
        if state.get("paused_at") == step:
            return state
        time.sleep(0.02)
    raise AssertionError(f"trace 未在步骤 {step} 暂停,state={state}")


def test_live_debug_mode_c_e2e(session):
    """Mode C e2e:运行中 attach → 设断 → 暂停 → 步进 → 改输入 → 继续 → 落盘见差异。

    覆盖 spec live-debug:附加即生效 / 断点命中暂停 / 单步 / 暂停点输入替换后继续;
    全部走真实 HTTP 契约(spec 实时双向消息 / 面板指令实时送达执行侧)。
    """
    import threading

    base = session.url
    holder: dict = {}
    start = threading.Event()
    done = threading.Event()

    def _agent_run():
        try:
            with session.trace() as tid:
                holder["tid"] = tid
                start.wait(15)  # 等面板完成 attach + 设断再放行(全量负载下放宽预算)
                holder["outs"] = run_agent(
                    session.interceptor, 5, FakeLLM(["s0", "s1", "s2", "s3", "s4"])
                )
        finally:
            done.set()

    th = threading.Thread(target=_agent_run, daemon=True)
    th.start()

    # 等待 trace 建立(running)
    tid = None
    deadline = time.time() + 15
    while time.time() < deadline:
        tid = holder.get("tid")
        if tid:
            break
        time.sleep(0.02)
    assert tid is not None, "agent trace 未在预期时间内建立"

    # ---- attach ----
    st, state = _post(base, f"/api/debug/{tid}/attach", {})
    assert st == 200 and state["attached"] is True

    # ---- 设断点:kind=llm(首个决策点命中)→ 暂停 step 0 ----
    st, bp = _post(base, f"/api/debug/{tid}/breakpoints", {"kind": "llm"})
    assert st == 200 and bp["kind"] == "llm"
    start.set()  # 放行 agent → 首个决策点命中断点暂停
    _wait_debug_paused(base, tid, 0)

    # ---- 单步 → step 1 ----
    st, _ = _post(base, f"/api/debug/{tid}/step", {})
    assert st == 200
    _wait_debug_paused(base, tid, 1)

    # ---- 改输入并继续:step 1 的 messages[0].content → "EDITED" ----
    st, res = _post(
        base,
        f"/api/debug/{tid}/modify",
        {"step": 1, "field": "input_context.messages[0].content", "value": "EDITED"},
    )
    assert st == 200 and res["ok"] is True

    # ---- 移除断点后继续放行 → agent 完成 ----
    st, res = _delete(base, f"/api/debug/{tid}/breakpoints/{bp['id']}")
    assert st == 200 and res["ok"] is True
    st, _ = _post(base, f"/api/debug/{tid}/continue", {})
    assert st == 200
    assert done.wait(5), "agent 在 remove+continue 后未完成"
    assert holder["outs"] == ["s0", "s1", "s2", "s3", "s4"]

    # ---- 落盘可见差异:step1 输入已替换为 EDITED,step0 仍为原输入 ----
    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]
    _st, pts = _get(base, f"/api/branches/{root}/points")
    by_step = {p["step_index"]: p for p in pts}
    assert by_step[0]["input_context"]["messages"][0]["content"] == "hi"
    assert by_step[1]["input_context"]["messages"][0]["content"] == "EDITED"
    assert [p["output"]["content"] for p in sorted(pts, key=lambda x: x["step_index"])] == [
        "s0",
        "s1",
        "s2",
        "s3",
        "s4",
    ]


def test_branch_diff_api_e2e(session):
    """分支 diff 接口:对齐步骤 + 字段级明细 + 汇总;分支缺失 404 / 跨 trace 支持。

    覆盖 spec branch-diff:分支步骤对齐与状态(共享前缀相同 / 分叉差异)、
    字段级差异明细(输出字段左右取值)、差异汇总(四类计数)、只读接口错误路径,
    以及 compare-traces spec:跨 trace 对比与来源标注。
    """
    base = session.url
    # 记录 root 分支:a,b,c
    with session.trace() as tid:
        run_agent(session.interceptor, 3, FakeLLM(["a", "b", "c"]))
    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]

    # 两个 fork 分支:同从 step1 分叉(进入待执行队列,按序消费)
    _st, f1 = _post(base, "/api/forks", {"trace_id": tid, "branch_id": root, "from_step": 1})
    assert _st == 200, f1
    _st, f2 = _post(base, "/api/forks", {"trace_id": tid, "branch_id": root, "from_step": 1})
    assert _st == 200, f2

    # 依次执行两分支:step0 前缀回放(不真调),step1/2 后缀真调
    with session.trace():
        run_agent(session.interceptor, 3, FakeLLM(["X", "Y"]))
    with session.trace():
        run_agent(session.interceptor, 3, FakeLLM(["Z", "W"]))

    # ---- diff:共享前缀 same,分叉后缀 diff ----
    _st, res = _get(base, f"/api/branches/{f1['branch']['id']}/diff/{f2['branch']['id']}")
    assert res["branch_a"] == f1["branch"]["id"]
    assert res["branch_b"] == f2["branch"]["id"]
    assert [s["status"] for s in res["steps"]] == ["same", "diff", "diff"]
    assert res["summary"] == {"same": 1, "diff": 2, "only_left": 0, "only_right": 0}
    # 字段明细:step1 输出 X vs Z
    step1 = next(s for s in res["steps"] if s["step_index"] == 1)
    field = next(f for f in step1["fields"] if f["path"] == "output.content")
    assert field["left"] == "X" and field["right"] == "Z" and field["status"] == "changed"

    # ---- 错误路径:分支缺失 404 ----
    st, body = _get_error(base, "/api/branches/does-not-exist/diff/does-not-exist")
    assert st == 404 and body.get("error")
    with session.trace() as tid2:
        run_agent(session.interceptor, 1, FakeLLM(["x"]))
    _st, data2 = _get(base, f"/api/traces/{tid2}")
    root2 = data2["trace"]["root_branch_id"]
    # ---- 跨 trace 对比(spec compare-traces):不再 422,返回对齐步骤 + 来源标注 ----
    _st, xt = _get(base, f"/api/branches/{root}/diff/{root2}")
    assert _st == 200
    # 三 vs 一步骤:右 trace 仅 step0(3 步 vs 1 步前两段只在左)
    statuses = [s["status"] for s in xt["steps"]]
    assert statuses[0] == "diff", statuses  # step0 内容不同
    assert statuses[1] == "only_left" and statuses[2] == "only_left", statuses
    assert xt["summary"] == {"same": 0, "diff": 1, "only_left": 2, "only_right": 0}
    # 来源标注:两侧 trace 的 agent_name
    assert xt["trace_a"] and xt["trace_b"]
    assert len(xt["steps"]) == 3

    # ---- 全局分支索引(spec compare-traces):所有 trace 分支 + 所属 trace 标签 ----
    _st, allb = _get(base, "/api/branches")
    assert _st == 200
    by_id = {b["id"]: b for b in allb}
    # 两侧 trace 的分支都在索引内,且带 trace 标签
    assert root in by_id and root2 in by_id
    assert {root, root2}.issubset({b["id"] for b in allb})
    labels = {b["trace_name"] for b in allb}
    assert all(b.get("trace_id") for b in allb)
    # 分支 id 全索引唯一(可作为下拉选项键)
    ids = [b["id"] for b in allb]
    assert len(ids) == len(set(ids))
    assert labels  # 至少含一个 trace 名
