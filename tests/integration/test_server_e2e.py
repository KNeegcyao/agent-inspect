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

    # ---- attach(重试安全:以 GET state 为准断言,避免重复投递的 attached=False 干扰)----
    st, _ = _post(base, f"/api/debug/{tid}/attach", {})
    assert st == 200
    _st, state = _get(base, f"/api/debug/{tid}/state")
    assert state["attached"] is True

    # ---- 设断点:kind=llm(首个决策点命中)→ 暂停 step 0 ----
    st, bp = _post(base, f"/api/debug/{tid}/breakpoints", {"kind": "llm"})
    assert st == 200 and bp["kind"] == "llm"
    start.set()  # 放行 agent → 首个决策点命中断点暂停
    _wait_debug_paused(base, tid, 0)

    # ---- 单步 → step 1(携带 at_step:重复/迟到投递不会误放新暂停点)----
    st, res = _post(base, f"/api/debug/{tid}/step", {"at_step": 0})
    assert st == 200 and res["released"] is True
    _wait_debug_paused(base, tid, 1)

    # ---- 改输入并继续:step 1 的 messages[0].content → "EDITED" ----
    st, res = _post(
        base,
        f"/api/debug/{tid}/modify",
        {"step": 1, "field": "input_context.messages[0].content", "value": "EDITED"},
    )
    assert st == 200 and res["ok"] is True

    # ---- 移除断点后继续放行 → agent 完成(continue 同样绑定暂停点)----
    st, res = _delete(base, f"/api/debug/{tid}/breakpoints/{bp['id']}")
    assert st == 200 and res["ok"] is True
    _st, dstate = _get(base, f"/api/debug/{tid}/state")
    st, _ = _post(base, f"/api/debug/{tid}/continue", {"at_step": dstate.get("paused_at")})
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


def test_adopt_diff_to_fork_e2e(session):
    """采纳差异:只读预览映射修改清单 → 确认创建 Fork → 采纳后的修改在分支上生效。

    覆盖 spec adopt-diff-to-fork:生成采纳修改(输入/输出映射)、只读预览不创建分支、
    预览 → 确认 → 复用 /api/forks 创建、错误路径(404/422)。
    """
    base = session.url
    # 记录 root 分支:a,b,c
    with session.trace() as tid:
        run_agent(session.interceptor, 3, FakeLLM(["a", "b", "c"]))
    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]

    # 对比分支:从 step1 分叉,后缀真调 X,Y(step0 前缀回放 a)
    _st, f1 = _post(base, "/api/forks", {"trace_id": tid, "branch_id": root, "from_step": 1})
    assert _st == 200, f1
    fork_branch = f1["branch"]["id"]
    with session.trace():
        run_agent(session.interceptor, 3, FakeLLM(["X", "Y"]))

    before = len(_get(base, f"/api/traces/{tid}")[1]["branches"])

    # ---- 1) 只读预览:差异 → 修改清单,不创建分支 ----
    _st, res = _post(
        base,
        f"/api/branches/{root}/diff/{fork_branch}/adopt",
        {"from_step": 1},
    )
    assert _st == 200, res
    assert res["dry_run"] is True
    assert res["branch_a"] == root and res["branch_b"] == fork_branch
    # step1(b vs X)与 step2(c vs Y)各一条 output 整段覆盖,值取右侧完整输出
    assert res["modifications"] == [
        {"step": 1, "field": "output", "value": {"content": "X"}},
        {"step": 2, "field": "output", "value": {"content": "Y"}},
    ]
    # 只读:分支集合不变
    after = len(_get(base, f"/api/traces/{tid}")[1]["branches"])
    assert before == after

    # ---- 2) steps 过滤:只采纳指定步骤 ----
    _st, filtered = _post(
        base,
        f"/api/branches/{root}/diff/{fork_branch}/adopt",
        {"from_step": 1, "steps": [1]},
    )
    assert _st == 200, filtered
    assert [m["step"] for m in filtered["modifications"]] == [1]

    # ---- 3) 确认创建 Fork:复用 /api/forks,采纳的修改在分支上生效 ----
    _st, created = _post(
        base,
        "/api/forks",
        {
            "trace_id": tid,
            "branch_id": root,
            "from_step": 1,
            "modifications": res["modifications"],
            "note": "adopt e2e",
        },
    )
    assert _st == 200, created
    adopted = created["branch"]
    assert adopted["origin"] == "fork" and adopted["branch_from_step"] == 1

    # 执行采纳分支:step0 前缀回放 a;step1/2 注入完整 output 覆盖 X/Y,不真调
    with session.trace():
        llm = FakeLLM(["ignored"])
        outs = run_agent(session.interceptor, 3, llm)
    assert outs == ["a", {"content": "X"}, {"content": "Y"}]
    assert llm.calls == 0  # 采纳的 output 覆盖均不真调

    # ---- 4) 错误路径 ----
    st, body = _post(base, "/api/branches/does-not-exist/diff/x/adopt", {"from_step": 0})
    assert st == 404 and body.get("error")
    st, body = _post(base, f"/api/branches/{root}/diff/{fork_branch}/adopt", {"from_step": 999})
    assert st == 422 and body.get("error")
    st, body = _post(base, f"/api/branches/{root}/diff/{fork_branch}/adopt", {"from_step": "bad"})
    assert st == 422 and body.get("error")


def test_adopt_cross_trace_e2e(session):
    """跨 trace 采纳:另一 trace 的值 → 主 trace 新分支,来源标注 + 归属校验。

    覆盖 spec adopt-cross-trace:跨 trace 采纳预览(来源标注)、只读预览无副作用、
    确认创建于主 trace、采纳值跨 trace 生效、父分支归属校验。
    """
    base = session.url
    # trace A:a,b,c
    with session.trace() as tidA:
        run_agent(session.interceptor, 3, FakeLLM(["a", "b", "c"]))
    _st, dataA = _get(base, f"/api/traces/{tidA}")
    rootA = dataA["trace"]["root_branch_id"]
    # trace B:X,Y,Z
    with session.trace() as tidB:
        run_agent(session.interceptor, 3, FakeLLM(["X", "Y", "Z"]))
    _st, dataB = _get(base, f"/api/traces/{tidB}")
    rootB = dataB["trace"]["root_branch_id"]
    assert tidA != tidB

    before = len(_get(base, f"/api/traces/{tidA}")[1]["branches"])

    # ---- 1) 跨 trace 采纳预览:来源标注 + 值取自 trace B ----
    _st, res = _post(base, f"/api/branches/{rootA}/diff/{rootB}/adopt", {"from_step": 0})
    assert _st == 200, res
    assert res["dry_run"] is True
    assert res["trace_id_a"] != res["trace_id_b"]
    assert res["trace_a"] and res["trace_b"]
    assert res["modifications"] == [
        {"step": 0, "field": "output", "value": {"content": "X"}},
        {"step": 1, "field": "output", "value": {"content": "Y"}},
        {"step": 2, "field": "output", "value": {"content": "Z"}},
    ]
    # 只读:主 trace 分支集合不变
    after = len(_get(base, f"/api/traces/{tidA}")[1]["branches"])
    assert before == after

    # ---- 2) 确认创建:新分支落在主 trace ----
    _st, created = _post(
        base,
        "/api/forks",
        {
            "trace_id": tidA,
            "branch_id": rootA,
            "from_step": 0,
            "modifications": res["modifications"],
            "note": "adopt cross-trace e2e",
        },
    )
    assert _st == 200, created
    adopted = created["branch"]
    assert adopted["origin"] == "fork" and adopted["branch_from_step"] == 0
    assert adopted["trace_id"] == tidA  # 创建于主 trace

    # ---- 3) 执行:采纳值跨 trace 生效,输出覆盖不真调 ----
    with session.trace():
        llm = FakeLLM(["ignored"])
        outs = run_agent(session.interceptor, 3, llm)
    assert outs == [{"content": "X"}, {"content": "Y"}, {"content": "Z"}]
    assert llm.calls == 0

    # ---- 4) 归属校验:父分支不属于目标 trace → 422 ----
    st, body = _post(base, "/api/forks", {"trace_id": tidA, "branch_id": rootB, "from_step": 0})
    assert st == 422 and body.get("error")
    assert "belongs to trace" in body["error"]


def test_fork_sandbox_e2e(session):
    """带沙箱的 Fork 全链路:工具 dry-run 无真调 + meta 标记、LLM 照常真调、非法配置 422。

    覆盖 spec fork.副作用沙箱:按 kind 配置策略 / 工具 dry-run 模拟 / 未配置保持真调 / 非法配置拒绝。
    """
    base = session.url
    with session.trace() as tid:
        run_agent(session.interceptor, 2, FakeLLM(["a", "b"]))
    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]

    # ---- 1) 带 sandbox 发起 Fork ----
    st, res = _post(
        base,
        "/api/forks",
        {
            "trace_id": tid,
            "branch_id": root,
            "from_step": 0,
            "sandbox": {"tool": "dry-run"},
            "note": "sandbox e2e",
        },
    )
    assert st == 200, res
    fork_branch = res["branch"]
    assert fork_branch["origin"] == "fork"

    # ---- 2) 执行:工具 dry-run 不真调,LLM 照常真调 ----
    with session.trace():
        tool_llm = FakeLLM(["X", "Y"])
        outs_tool = run_agent(session.interceptor, 2, tool_llm, kind="tool")
        llm_llm = FakeLLM(["Z"])
        outs_llm = run_agent(session.interceptor, 1, llm_llm, kind="llm")
    assert outs_tool == [None, None]
    assert tool_llm.calls == 0  # 工具被沙箱拦下,无真实调用
    assert outs_llm == ["Z"]
    assert llm_llm.calls == 1  # LLM 未配置 → 照常真调

    # ---- 3) 决策点经 API 读取沙箱标记 ----
    _st, fpts = _get(base, f"/api/branches/{fork_branch['id']}/points")
    assert [p["kind"] for p in fpts] == ["tool", "tool", "llm"]
    assert all(p["meta"].get("sandbox") == "dry-run" for p in fpts if p["kind"] == "tool")
    assert all("sandbox" not in p["meta"] for p in fpts if p["kind"] == "llm")

    # ---- 4) 非法 sandbox 配置 → 422,不落库 ----
    st, body = _post(
        base,
        "/api/forks",
        {"trace_id": tid, "branch_id": root, "from_step": 0, "sandbox": {"tool": "bogus"}},
    )
    assert st == 422 and body.get("error")
    assert "invalid sandbox policy" in body["error"]
    branches = _get(base, f"/api/traces/{tid}")[1]["branches"]
    assert {b["id"] for b in branches} == {root, fork_branch["id"]}  # 未新增分支


def test_fork_sandbox_llm_e2e(session):
    """LLM 决策点沙箱全链路:LLM dry-run 无真调 + meta 标记、工具未配置照常真调、混合配置独立生效。

    覆盖 spec fork.LLM 决策点沙箱:LLM dry-run 模拟 / LLM block 阻止 / 混合配置按 kind 独立生效。
    """
    base = session.url
    with session.trace() as tid:
        run_agent(session.interceptor, 2, FakeLLM(["a", "b"]))
    _st, data = _get(base, f"/api/traces/{tid}")
    root = data["trace"]["root_branch_id"]

    # ---- 1) 带 LLM sandbox 发起 Fork ----
    st, res = _post(
        base,
        "/api/forks",
        {
            "trace_id": tid,
            "branch_id": root,
            "from_step": 0,
            "sandbox": {"llm": "dry-run"},
            "note": "llm sandbox e2e",
        },
    )
    assert st == 200, res
    fork_branch = res["branch"]
    assert fork_branch["origin"] == "fork"

    # ---- 2) 执行:LLM dry-run 不真调,工具未配置照常真调 ----
    with session.trace():
        llm_llm = FakeLLM(["X", "Y"])
        outs_llm = run_agent(session.interceptor, 2, llm_llm, kind="llm")
        tool_llm = FakeLLM(["Z"])
        outs_tool = run_agent(session.interceptor, 1, tool_llm, kind="tool")
    assert outs_llm == [None, None]
    assert llm_llm.calls == 0  # LLM 被沙箱拦下,无真实调用
    assert outs_tool == ["Z"]
    assert tool_llm.calls == 1  # 工具未配置 → 照常真调

    # ---- 3) 决策点经 API 读取沙箱标记 ----
    _st, fpts = _get(base, f"/api/branches/{fork_branch['id']}/points")
    assert [p["kind"] for p in fpts] == ["llm", "llm", "tool"]
    assert all(p["meta"].get("sandbox") == "dry-run" for p in fpts if p["kind"] == "llm")
    assert all("sandbox" not in p["meta"] for p in fpts if p["kind"] == "tool")

    # ---- 4) 混合配置 {llm: block, tool: allow}:LLM 拦下、工具照常真调 ----
    st, res2 = _post(
        base,
        "/api/forks",
        {"trace_id": tid, "branch_id": root, "from_step": 0, "sandbox": {"llm": "block", "tool": "allow"}},
    )
    assert st == 200, res2
    fork2 = res2["branch"]
    with session.trace():
        llm2 = FakeLLM(["X"])
        outs2_llm = run_agent(session.interceptor, 1, llm2, kind="llm")
        tool2 = FakeLLM(["Z"])
        outs2_tool = run_agent(session.interceptor, 1, tool2, kind="tool")
    assert outs2_llm == [None]
    assert llm2.calls == 0
    assert outs2_tool == ["Z"]
    assert tool2.calls == 1
    _st, fpts2 = _get(base, f"/api/branches/{fork2['id']}/points")
    assert fpts2[0]["kind"] == "llm" and fpts2[0]["meta"].get("sandbox") == "blocked"
    assert fpts2[1]["kind"] == "tool" and "sandbox" not in fpts2[1]["meta"]


def test_trace_import_e2e(session):
    """导入外部 span 导出 JSON → imported 标记 → 对导入 trace 发起 Fork;非法导入 422 不落库。

    覆盖 spec trace-import:导入映射(LLM/工具 span → 决策点)/ 与既有调试流打通
    (查看、Fork 前缀回放导入输出)/ 非法导入可观测拒绝。
    """
    base = session.url

    def _llm_span(span_id, parent, content, out, start):
        return {
            "span_id": span_id,
            "parent_span_id": parent,
            "name": f"llm-{span_id}",
            "start_time": start,
            "end_time": start + 15,
            "attributes": {
                "openinference.span.kind": "LLM",
                "llm.model_name": "gpt-test",
                "llm.input_messages.0.message.role": "user",
                "llm.input_messages.0.message.content": content,
                "llm.output_messages.0.message.content": out,
            },
        }

    export = {
        "agent_name": "imported-prod",
        "spans": [
            _llm_span("s1", None, "hi", "s0", 1720000000000),
            _llm_span("s2", "s1", "go on", "s1", 1720000000010),
            _llm_span("s3", "s2", "more", "s2", 1720000000020),
            {  # 无 kind → 忽略并计数
                "span_id": "sx",
                "name": "agent-run",
                "start_time": 1720000000005,
                "end_time": 1720000000008,
                "attributes": {},
            },
        ],
    }

    before = len(_traces(base))
    st, res = _post(base, "/api/traces/import", export)
    assert st == 200, res
    assert res["decision_points"] == 3 and res["skipped"] == 1
    tid = res["trace_id"]

    # 列表与详情带 imported 标记;历史运行 lifecycle=done
    traces = _traces(base)
    assert len(traces) == before + 1
    row = next(t for t in traces if t["id"] == tid)
    assert row["imported"] is True and row["lifecycle"] == "done"
    _st, data = _get(base, f"/api/traces/{tid}")
    assert data["imported"] is True
    root = data["trace"]["root_branch_id"]

    # 决策点经既有查询读取:LLM span → llm 决策点,输入输出保真
    _st, pts = _get(base, f"/api/branches/{root}/points")
    assert [p["kind"] for p in pts] == ["llm", "llm", "llm"]
    assert [p["step_index"] for p in pts] == [0, 1, 2]
    assert pts[0]["input_context"]["messages"] == [{"role": "user", "content": "hi"}]
    assert pts[0]["input_context"]["model"] == "gpt-test"
    assert pts[0]["output"]["content"] == "s0"
    assert pts[0]["meta"]["imported"] is True

    # ---- 对导入链路发起 Fork:前缀回放导入输出(不真调),后缀真调 ----
    st, f1 = _post(base, "/api/forks", {"trace_id": tid, "branch_id": root, "from_step": 2})
    assert st == 200, f1
    with session.trace():
        llm = FakeLLM(["X"])
        outs = run_agent(session.interceptor, 3, llm)
    assert outs == ["s0", "s1", "X"]
    assert llm.calls == 1
    _st, fpts = _get(base, f"/api/branches/{f1['branch']['id']}/points")
    assert [p["output"]["content"] for p in fpts] == ["X"]

    # ---- 非法导入:422 + 可观测原因,不落库 ----
    st, body = _post(base, "/api/traces/import", {"foo": 1})
    assert st == 422 and body.get("error")
    st, body = _post(base, "/api/traces/import", {"spans": [{"name": "x", "attributes": {}}]})
    assert st == 422 and body.get("error")
    assert "no importable spans" in body["error"]
    assert len(_traces(base)) == before + 1


def test_cross_process_trace_e2e(session, tmp_path):
    """跨进程追踪:子进程带 env 记录 → 父 trace 的 children 含子 trace。

    覆盖 spec cross-process-trace:子进程通过 AGENT_INSPECT_PARENT_TRACE 声明父 trace,
    新记录 trace 落库携带 parent_trace_id,`GET /api/traces/{parent}` 的 children 含子 trace。
    """
    import os
    import subprocess
    import sys
    import textwrap

    base = session.url
    db_path = str(tmp_path / "e2e.db")
    root_dir = str(Path(__file__).resolve().parents[2])

    with session.trace() as tid:
        run_agent(session.interceptor, 1, FakeLLM(["parent"]))

    child_code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {root_dir!r})
        import agent_inspect
        from tests.conftest import FakeLLM, run_agent
        s = agent_inspect.start(db_path={db_path!r}, autostart_browser=False)
        try:
            with s.trace() as cid:
                run_agent(s.interceptor, 1, FakeLLM(["child"]))
            print("CHILD_TRACE=" + cid)
        finally:
            s.stop()
        """
    )
    env = {**os.environ, "AGENT_INSPECT_PARENT_TRACE": tid}
    proc = subprocess.run(
        [sys.executable, "-c", child_code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    child_id = next(
        (line.split("=", 1)[1] for line in proc.stdout.splitlines() if line.startswith("CHILD_TRACE=")),
        None,
    )
    assert child_id is not None, proc.stdout

    # 父 trace 的 children 含子 trace;子 trace 自身标记父引用
    _st, data = _get(base, f"/api/traces/{tid}")
    assert _st == 200
    assert data["trace"]["parent_trace_id"] is None
    assert child_id in {c["id"] for c in data["children"]}
    _st, cdata = _get(base, f"/api/traces/{child_id}")
    assert cdata["trace"]["parent_trace_id"] == tid
    # 列表接口每条带 parent_trace_id(UI 缩进 + 徽标的数据基础)
    _st, traces = _get(base, "/api/traces")
    by_id = {t["id"]: t for t in traces}
    assert by_id[tid]["parent_trace_id"] is None
    assert by_id[child_id]["parent_trace_id"] == tid
