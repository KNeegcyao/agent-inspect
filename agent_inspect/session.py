"""本地运行时:一行启用拦截 + 内嵌服务 + 自动开面板。

Session 负责把 store / recorder / interceptor / fork 控制器 / 插桩 / 内嵌服务
装配成一个进程内可用的调试运行时。`agent_inspect.start()` 即一键启用。
"""
from __future__ import annotations

import asyncio
import atexit
import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import uvicorn

from ._context import reset_cursor, set_cursor
from ._models import LIFECYCLE_ABORTED, LIFECYCLE_DONE
from ._server.app import EventHub, create_app
from ._server.store.queries import Store
from .debug import DebugController
from .fork import ForkController
from .interceptor.base import Interceptor
from .interceptor.langchain_patcher import LangChainPatcher
from .interceptor.openai_patcher import OpenAIPatcher
from .recorder import Recorder

DEFAULT_PORT = 8765
DEFAULT_DB = Path.home() / ".agent-inspect" / "agent-inspect.db"


def _default_ui_dir() -> Optional[Path]:
    """构建好的 React UI 目录:优先包内打包面板(pip 安装形态),再回退仓库 web/dist(开发形态);都没有则内嵌占位页。"""
    bundled = Path(__file__).resolve().parent / "panel"
    if (bundled / "index.html").is_file():
        return bundled
    repo = Path(__file__).resolve().parent.parent / "web" / "dist"
    return repo if (repo / "index.html").is_file() else None


class Session:
    """一次 `start()` 产生的调试会话。提供 `url`、`stop()`。"""

    def __init__(
        self,
        *,
        db_path: Optional[str] = None,
        port: int = DEFAULT_PORT,
        autostart_browser: bool = True,
        record_mode: str = "dev",
        blob_threshold: int = 4096,
        ui_dir: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.record_mode = record_mode
        self.ui_dir = Path(ui_dir) if ui_dir else _default_ui_dir()

        self.events = EventHub()
        self.store = Store(str(self.db_path))
        self.recorder = Recorder(
            self.store,
            record_mode=record_mode,
            blob_threshold=blob_threshold,
            on_event=self.events.publish,
            parent_trace_id=os.environ.get("AGENT_INSPECT_PARENT_TRACE"),
        )
        self.fork = ForkController(self.store)
        self.debug = DebugController(self.store, on_event=self.events.publish)
        self.interceptor = Interceptor(self.recorder, controller=self.fork, debug=self.debug)
        self._patchers = [LangChainPatcher(), OpenAIPatcher()]
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = False

        # ---- 启用拦截(非侵入:start 即装,stop 即卸)----
        for p in self._patchers:
            p.install(self.interceptor)

        # ---- 内嵌服务:择可用端口 ----
        self.port = _pick_port(self.port)
        self.app = create_app(self)
        self.url = f"http://127.0.0.1:{self.port}"

        self._start_server()

        if autostart_browser:
            self._open_browser()

        atexit.register(self.stop)

    # ------------------------------------------------------------------
    def _start_server(self) -> None:
        # Windows 上 uvicorn 在后台线程跑自己的事件循环:默认 Proactor 策略在
        # 非主线程里不会响应外部连接(同进程请求正常、外部请求挂起),必须改用
        # Selector 策略。全局设置一次即可,后续线程建循环时都生效。
        if sys.platform == "win32" and not isinstance(
            asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy
        ):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="agent-inspect-server"
        )
        self._thread.start()
        # 就绪等待:线程已启动 ≠ 端口已可接受连接;不等待的话启用后第一个请求会被拒
        # (Linux CI 上线程调度更慢,必现;对真实用户同样存在)。uvicorn 在绑定端口后才置 started。
        deadline = time.time() + 5
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("agent-inspect server failed to start within 5s")
            time.sleep(0.01)

    def _open_browser(self) -> None:
        """自动开浏览器;无图形/无浏览器环境静默降级为打印 URL。"""
        try:
            opened = webbrowser.open(self.url)
        except Exception:  # noqa: BLE001
            opened = False
        if not opened:
            print(f"[agent-inspect] 面板地址(无头环境): {self.url}")

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for p in self._patchers:
            p.uninstall()
        if self._server is not None:
            self._server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=3)
        self.store.close()

    # ---- 便捷查询 ----
    def list_traces(self, lifecycle: Optional[str] = None):
        return self.store.list_traces(lifecycle)

    # ---- 生命周期:终态标记 + 作用域 ----
    def finish_trace(self, trace_id: str, lifecycle: str = LIFECYCLE_DONE) -> None:
        """把 trace 标记为终态(done / aborted),供面板区分进行中/完成/中止。"""
        self.store.set_trace_lifecycle(trace_id, lifecycle)
        # 终态后该 trace 不再产生决策点,释放其调试门(断点已持久化,重附加可恢复)
        self.debug.drop_gate(trace_id)

    def abort_trace(self, trace_id: str) -> None:
        self.finish_trace(trace_id, LIFECYCLE_ABORTED)

    # ---- Mode C live 调试:面板指令直接送达到执行侧 ----
    def debug_attach(self, trace_id: str) -> dict:
        gate = self.debug.ensure_gate(trace_id)
        first = gate.attach()
        if first:
            self.events.publish("trace.attached", {"trace_id": trace_id})
        return gate.state()

    def debug_add_breakpoint(self, trace_id: str, **kw) -> dict:
        gate = self.debug.ensure_gate(trace_id)
        return gate.add_breakpoint(**kw).to_dict()

    def debug_remove_breakpoint(self, trace_id: str, bp_id: str) -> bool:
        gate = self.debug.gate(trace_id)
        if gate is None:
            return False
        return gate.remove_breakpoint(bp_id)

    def debug_pause(self, trace_id: str) -> None:
        gate = self.debug.gate(trace_id)
        if gate is not None:
            gate.pause()

    def debug_step(self, trace_id: str, at_step: Optional[int] = None) -> bool:
        gate = self.debug.gate(trace_id)
        if gate is None:
            return False
        return gate.step(at_step)

    def debug_continue(self, trace_id: str, at_step: Optional[int] = None) -> bool:
        gate = self.debug.gate(trace_id)
        if gate is None:
            return False
        return gate.resume(at_step)

    def debug_modify(self, trace_id: str, step: int, field: str, value) -> None:
        gate = self.debug.gate(trace_id)
        if gate is not None:
            gate.modify(step, field, value)
            self.events.publish(
                "point.modified",
                {"trace_id": trace_id, "step_index": step, "field": field},
            )

    def debug_state(self, trace_id: str) -> dict:
        gate = self.debug.gate(trace_id)
        return gate.state() if gate is not None else {"trace_id": trace_id, "attached": False}

    @contextmanager
    def trace(self, agent_name: str = "agent") -> Iterator[str]:
        """把一段 Agent 执行括进一个 trace 生命周期。

        进入时消费 pending fork(若有)或新建记录 trace;正常退出标记 done,
        异常退出标记 aborted 并原样抛出。yield 出 trace_id。

        ```python
        with session.trace() as trace_id:
            agent.run()   # 经拦截的 LLM/工具调用进入该 trace
        ```
        """
        cursor, trace_id, _branch = self.interceptor.acquire_context()
        token = set_cursor(cursor)
        try:
            yield trace_id
            self.finish_trace(trace_id)
        except BaseException:
            self.abort_trace(trace_id)
            raise
        finally:
            reset_cursor(token)


def _pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in [{preferred}, {preferred + 50})")


def start(**kwargs) -> Session:
    """一行启用:拦截 + 记录 + 内嵌面板 + 自动开浏览器。"""
    return Session(**kwargs)
