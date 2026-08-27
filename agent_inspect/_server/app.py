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

    @app.get("/api/branches/{branch_id}/points")
    def branch_points_route(branch_id: str):
        return _branch_points(branch_id)

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
            )
        except Exception as e:  # noqa: BLE001 - 校验失败以可观测原因返回
            return JSONResponse({"error": str(e)}, status_code=422)
        return {"branch": branch.to_dict(), "plan": plan.__dict__}

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
    }
