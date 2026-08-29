"""内嵌调试服务:FastAPI 应用工厂 + 事件订阅。

同一进程内托管 REST/SSE,无独立后端。UI(React 单页)消费这些接口。
UI 为 `web/` 下 Vite 构建产物(`web/dist`),存在时以 SPA 方式托管;否则回退到内嵌占位页。
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import _models as m
from ..adopt import preview_adopt
from ..diff import diff_branches
from ..fork import Modification


class EventHub:
    """进程内事件广播(SSE 消费端订阅)。"""

    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def publish(self, event: str, payload) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put((event, payload))

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


_INDEX_HTML = """<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>Agent-Inspect</title>
<style>
  body{font-family:ui-monospace,Consolas,monospace;margin:2rem;background:#0f1420;color:#dbe4ff}
  a{color:#6ea8ff}pre{background:#161d2e;padding:1rem;border-radius:8px;overflow:auto}
  h2{color:#8ab4ff}
</style></head>
<body>
<h1>Agent-Inspect 本地面板</h1>
<p>React 单页 UI 见任务 5;当前提供 <b>API</b> 接口与 <b>SSE 实时流</b>。</p>
<h2>Traces</h2>
<div id="traces">加载中…</div>
<h2>实时事件</h2>
<pre id="events">(等待决策点…)</pre>
<script>
const base = location.origin;
fetch(base + "/api/traces").then(r=>r.json()).then(list=>{
  document.getElementById("traces").innerHTML =
    list.length ? "<ul>" + list.map(t=>
      `<li><a href="${base}/api/traces/${t.id}">${t.id}</a> · ${t.agent_name} · ${t.lifecycle}</li>`
    ).join("") + "</ul>" : "(空)";
});
const es = new EventSource(base + "/api/events");
es.onmessage = e => {
  const pre = document.getElementById("events");
  pre.textContent = e.data + "\\n" + pre.textContent;
};
</script>
</body></html>
"""


def create_app(session) -> FastAPI:
    """构建 FastAPI 应用。session 提供 store / recorder / fork 控制器。"""
    app = FastAPI(title="Agent-Inspect", version="0.1.0")

    def _branch_points(branch_id: str) -> list[dict]:
        branch = session.store.get_branch(branch_id)
        if branch is None:
            return []
        points = session.store.get_decision_points(branch.trace_id, branch_id)
        return [session.recorder.serializer.resolve_dp(session.store, p, session.recorder.context_snap) for p in points]

    # ---- traces ----
    @app.get("/api/traces")
    def list_traces(lifecycle: Optional[str] = None):
        return [t.to_dict() for t in session.store.list_traces(lifecycle)]

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str):
        t = session.store.get_trace(trace_id)
        if t is None:
            return JSONResponse({"error": "trace not found"}, status_code=404)
        branches = session.store.list_branches(trace_id)
        return {
            "trace": t.to_dict(),
            "branches": [b.to_dict() for b in branches],
            "children": [c.to_dict() for c in session.store.list_child_traces(trace_id)],
        }

    @app.post("/api/traces/{trace_id}/lifecycle")
    async def set_trace_lifecycle_route(trace_id: str, request: Request):
        """显式标记终态(done / aborted),供脚本或面板使用(spec 生命周期终态)。"""
        if session.store.get_trace(trace_id) is None:
            return JSONResponse({"error": "trace not found"}, status_code=404)
        body = await request.json()
        lc = body.get("lifecycle")
        if lc not in (m.LIFECYCLE_DONE, m.LIFECYCLE_ABORTED):
            return JSONResponse({"error": f"invalid lifecycle: {lc}"}, status_code=422)
        session.finish_trace(trace_id, lc)
        return {"ok": True, "trace_id": trace_id, "lifecycle": lc}

    @app.get("/api/branches")
    def list_branches_all():
        """全局分支索引:所有 trace 的分支并附带所属 trace 标签,供跨 trace 对比分组。"""
        out = []
        for t in session.store.list_traces():
            for b in session.store.list_branches(t.id):
                d = b.to_dict()
                d["trace_id"] = t.id
                d["trace_name"] = t.agent_name or t.id
                d["trace_lifecycle"] = t.lifecycle
                out.append(d)
        return out

    @app.get("/api/branches/{branch_id}/points")
    def branch_points_route(branch_id: str):
        return _branch_points(branch_id)

    @app.get("/api/branches/{branch_a}/diff/{branch_b}")
    def branch_diff_route(branch_a: str, branch_b: str):
        """两分支完整链路 diff:对齐步骤(same/diff/only_left/only_right)+ 字段级明细 + 汇总。

        允许跨 trace:两条不同运行的记录也按 step_index 对齐比较(spec 跨 trace 对比)。
        """
        ba = session.store.get_branch(branch_a)
        bb = session.store.get_branch(branch_b)
        if ba is None or bb is None:
            return JSONResponse({"error": "branch not found"}, status_code=404)
        result = diff_branches(
            session.store,
            session.recorder.serializer,
            session.recorder.context_snap,
            branch_a,
            branch_b,
        )
        # 附带左右表达来源,供 UI 跨 trace 标注归属
        ta = session.store.get_trace(ba.trace_id)
        tb = session.store.get_trace(bb.trace_id)
        result["trace_a"] = ta.agent_name if ta else ba.trace_id
        result["trace_b"] = tb.agent_name if tb else bb.trace_id
        return result

    @app.post("/api/branches/{branch_a}/diff/{branch_b}/adopt")
    async def branch_diff_adopt_route(branch_a: str, branch_b: str, request: Request):
        """把 diff 差异采纳为对 branch_a 的 Fork 修改(只读预览)。

        校验:分支缺失 404;空链/起点越界 422(与 fork.request_fork 一致)。
        只读:仅计算修改列表,不创建分支、不发真实调用;确认后由 /api/forks 创建。
        """
        ba = session.store.get_branch(branch_a)
        bb = session.store.get_branch(branch_b)
        if ba is None or bb is None:
            return JSONResponse({"error": "branch not found"}, status_code=404)
        body = await request.json()
        try:
            from_step = int(body.get("from_step", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "from_step must be an int"}, status_code=422)
        steps = body.get("steps")
        if steps is not None:
            try:
                steps = [int(x) for x in steps]
            except (TypeError, ValueError):
                return JSONResponse({"error": "steps must be a list of ints"}, status_code=422)
        note = body.get("note")
        # 与 fork.request_fork 相同的校验,预览不落库
        if session.store.count_decision_points(ba.trace_id) == 0:
            return JSONResponse(
                {"error": f"cannot adopt onto empty trace {ba.trace_id}: no decision points recorded yet"},
                status_code=422,
            )
        last = session.store.last_step_before(branch_a, 2**31 - 1) or 0
        if from_step < 0 or from_step > last + 1:
            return JSONResponse(
                {"error": f"adopt step {from_step} out of range for branch {branch_a} (0..{last + 1})"},
                status_code=422,
            )
        result = preview_adopt(
            session.store,
            session.recorder.serializer,
            session.recorder.context_snap,
            branch_a,
            branch_b,
            from_step,
            steps=steps,
            note=note,
        )
        return result

    # ---- fork ----
    @app.post("/api/forks")
    async def create_fork(request: Request):
        body = await request.json()
        mods = [
            Modification(step=int(x["step"]), field=x["field"], value=x.get("value"))
            for x in body.get("modifications", [])
        ]
        try:
            branch, plan = session.fork.request_fork(
                trace_id=body["trace_id"],
                from_branch=body.get("from_branch") or body["branch_id"],
                from_step=int(body["from_step"]),
                modifications=mods,
                dry_run=bool(body.get("dry_run", False)),
                note=body.get("note"),
                sandbox=body.get("sandbox"),
            )
        except Exception as e:  # noqa: BLE001 - 校验失败以可观测原因返回
            return JSONResponse({"error": str(e)}, status_code=422)
        return {"branch": branch.to_dict(), "plan": plan.__dict__}

    # ---- Mode C live 调试 ----
    def _require_running_trace(trace_id: str):
        t = session.store.get_trace(trace_id)
        if t is None:
            return None, JSONResponse({"error": "trace not found"}, status_code=404)
        if t.lifecycle != m.LIFECYCLE_RUNNING:
            return None, JSONResponse(
                {"error": f"trace not running (lifecycle={t.lifecycle})"}, status_code=422
            )
        return t, None

    @app.post("/api/debug/{trace_id}/attach")
    async def debug_attach(trace_id: str):
        _t, err = _require_running_trace(trace_id)
        if err is not None:
            return err
        return session.debug_attach(trace_id)

    @app.get("/api/debug/{trace_id}/state")
    def debug_state(trace_id: str):
        return session.debug_state(trace_id)

    @app.get("/api/debug/{trace_id}/breakpoints")
    def debug_list_breakpoints(trace_id: str):
        if session.store.get_trace(trace_id) is None:
            return JSONResponse({"error": "trace not found"}, status_code=404)
        gate = session.debug.gate(trace_id)
        return [b.to_dict() for b in (gate.breakpoints if gate else session.store.list_breakpoints(trace_id))]

    @app.post("/api/debug/{trace_id}/breakpoints")
    async def debug_add_breakpoint(trace_id: str, request: Request):
        _t, err = _require_running_trace(trace_id)
        if err is not None:
            return err
        body = await request.json()
        kind = body.get("kind") or None
        if kind is not None and kind not in (m.KIND_LLM, m.KIND_TOOL):
            return JSONResponse({"error": f"invalid kind: {kind}"}, status_code=422)
        bp = session.debug_add_breakpoint(
            trace_id,
            kind=kind,
            agent_id=body.get("agent_id") or None,
            condition=body.get("condition") or None,
        )
        return bp

    @app.delete("/api/debug/{trace_id}/breakpoints/{bp_id}")
    def debug_remove_breakpoint(trace_id: str, bp_id: str):
        if session.debug_remove_breakpoint(trace_id, bp_id):
            return {"ok": True, "breakpoint_id": bp_id}
        return JSONResponse({"error": "breakpoint not found"}, status_code=404)

    @app.post("/api/debug/{trace_id}/pause")
    async def debug_pause(trace_id: str):
        _t, err = _require_running_trace(trace_id)
        if err is not None:
            return err
        session.debug_pause(trace_id)
        return {"ok": True, "action": "pause"}

    @app.post("/api/debug/{trace_id}/step")
    async def debug_step(trace_id: str):
        _t, err = _require_running_trace(trace_id)
        if err is not None:
            return err
        session.debug_step(trace_id)
        return {"ok": True, "action": "step"}

    @app.post("/api/debug/{trace_id}/continue")
    async def debug_continue(trace_id: str):
        _t, err = _require_running_trace(trace_id)
        if err is not None:
            return err
        session.debug_continue(trace_id)
        return {"ok": True, "action": "continue"}

    @app.post("/api/debug/{trace_id}/modify")
    async def debug_modify(trace_id: str, request: Request):
        _t, err = _require_running_trace(trace_id)
        if err is not None:
            return err
        body = await request.json()
        if "step" not in body or "field" not in body or "value" not in body:
            return JSONResponse({"error": "step/field/value required"}, status_code=422)
        session.debug_modify(
            trace_id,
            step=int(body["step"]),
            field=str(body["field"]),
            value=body["value"],
        )
        return {"ok": True, "action": "modify", "step": int(body["step"])}

    # ---- 实时事件(SSE)----
    @app.get("/api/events")
    async def events():
        q = session.events.subscribe()

        async def gen():
            try:
                yield "retry: 1000\n\n"
                while True:
                    event, payload = await _aget(q)
                    data = json.dumps(payload, ensure_ascii=False, default=str)
                    yield f"event: {event}\ndata: {data}\n\n"
            finally:
                session.events.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---- SPA 托管:置于 API 路由之后注册,避免 `/{path}` 兜底吞掉 /api/* ----
    _mount_ui(app, getattr(session, "ui_dir", None))

    return app


async def _aget(q: queue.Queue):
    """取事件队列,超时返回 ping。

    关键:不能直接 `q.get(timeout=...)` 阻塞事件循环——那会让单线程 uvicorn
    在等待期间无法处理任何其它请求(浏览器开着 SSE 时其它 API 全部挂起)。
    用 `asyncio.to_thread` 把阻塞读放到线程池,事件循环保持空闲。
    """
    while True:
        try:
            return await asyncio.to_thread(q.get, timeout=15)
        except queue.Empty:
            return ("ping", {"type": "ping"})


def _mount_ui(app: FastAPI, ui_dir: Optional[Path]) -> None:
    """挂载 React 单页(web/dist);无构建产物时回退到内嵌占位页。

    - `/assets/*` 由 Vite 静态资源目录提供。
    - `/` 与任意非 API 路径以 SPA 方式返回 index.html(client 路由与刷新不 404)。
    - `/api/*` 之外的路径不拦截,交由业务路由处理。
    """
    if ui_dir is None or not (ui_dir / "index.html").is_file():
        @app.get("/", include_in_schema=False)
        def placeholder_index():
            return HTMLResponse(_INDEX_HTML)
        return

    assets = ui_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", include_in_schema=False)
    def spa_index():
        return FileResponse(ui_dir / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        candidate = ui_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(ui_dir / "index.html")


def trace_payload(session, trace_id: str) -> dict:
    t = session.store.get_trace(trace_id)
    if t is None:
        return {}
    branches = session.store.list_branches(trace_id)
    return {
        "trace": t.to_dict(),
        "branches": [b.to_dict() for b in branches],
        "children": [c.to_dict() for c in session.store.list_child_traces(trace_id)],
    }
