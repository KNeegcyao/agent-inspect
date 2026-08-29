"""推送测试(spec `trace-push`)。

用标准库 http.server 起线程 mock 收集端点,覆盖:载荷与导出映射逐字段一致
(scope 声明 + span kind)、送达统计、非 2xx / 不可达错误、推送只读不落库。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_inspect.exporter import export_trace
from agent_inspect.pusher import PushError, push_trace

from tests.unit.test_exporter import _seed_chain  # 复用导入链路种子


class _Collector:
    """mock 收集端点:捕获请求,可配置响应状态。"""

    def __init__(self, status=200):
        collector = self
        self.status = status
        self.requests: list[dict] = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                collector.requests.append(
                    {
                        "path": self.path,
                        "content_type": self.headers.get("Content-Type"),
                        "body": body,
                    }
                )
                self.send_response(collector.status)
                self.end_headers()

            def log_message(self, *a):  # 静默
                pass

        self._server = HTTPServer(("127.0.0.1", 0), H)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def _spans_of(payload: dict) -> list[dict]:
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"]


def test_push_payload_matches_export_mapping(env):
    """载荷与导出同一 trace 的映射逐字段一致,并带 scope 声明与 span kind(spec trace-push.推送映射)。"""
    tid, root = _seed_chain(env)
    with _Collector() as collector:
        res = push_trace(
            env.store, env.recorder, tid, f"http://127.0.0.1:{collector.port}/v1/traces"
        )

    assert res.delivered_spans == 3
    assert res.status_code == 200
    assert res.endpoint.endswith("/v1/traces")

    req = collector.requests[0]
    assert req["path"] == "/v1/traces"
    assert req["content_type"] == "application/json"
    payload = json.loads(req["body"].decode("utf-8"))

    # scope 声明与 span kind
    ss = payload["resourceSpans"][0]["scopeSpans"][0]
    assert ss["scope"] == {"name": "agent-inspect"}
    kinds = [s["kind"] for s in _spans_of(payload)]
    assert kinds == [3, 1, 3]  # LLM=CLIENT, TOOL=INTERNAL, LLM=CLIENT

    # 与导出信封逐字段一致(除新增 kind/scope 字段)
    envelope = export_trace(env.store, env.recorder, tid)
    for pushed, exported in zip(_spans_of(payload), _spans_of(envelope)):
        for k, v in exported.items():
            assert pushed[k] == v


def test_push_success_stats_and_readonly(env):
    """2xx → 回报送达 span 数;推送只读,本地 trace/分支集合不变(spec trace-push.送达统计)。"""
    tid, root = _seed_chain(env)
    before_traces = len(env.store.list_traces())
    before_branches = len(env.store.list_branches(tid))
    with _Collector() as collector:
        res = push_trace(env.store, env.recorder, tid, f"http://127.0.0.1:{collector.port}/v1/traces")
    assert res.delivered_spans == 3
    assert len(env.store.list_traces()) == before_traces
    assert len(env.store.list_branches(tid)) == before_branches


def test_push_non_2xx_observable(env):
    """端点非 2xx → PushError 含状态码,不发生本地写入(spec trace-push.非 2xx)。"""
    tid, _root = _seed_chain(env)
    before = len(env.store.list_traces())
    with _Collector(status=500) as collector:
        with pytest.raises(PushError) as ei:
            push_trace(env.store, env.recorder, tid, f"http://127.0.0.1:{collector.port}/v1/traces")
    assert "500" in str(ei.value)
    assert len(env.store.list_traces()) == before


def test_push_unreachable_observable(env):
    """端点不可达 → PushError 含 unreachable 原因(spec trace-push.端点不可达)。"""
    tid, _root = _seed_chain(env)
    # 关闭端口:起后立即停,端口大概率不再监听
    with _Collector() as collector:
        dead_port = collector.port
    with pytest.raises(PushError) as ei:
        push_trace(env.store, env.recorder, tid, f"http://127.0.0.1:{dead_port}/v1/traces", timeout=2.0)
    assert "unreachable" in str(ei.value)


def test_push_missing_trace_rejected(env):
    with pytest.raises(PushError) as ei:
        with _Collector() as collector:
            push_trace(env.store, env.recorder, "tr_none", f"http://127.0.0.1:{collector.port}/v1/traces")
    assert "not found" in str(ei.value)
