"""trace 决策链推送到标准 span 推送协议收集端点(HTTP + JSON 形态,OTLP/JSON)。

载荷复用 exporter.export_trace 的 span 映射(与导出文件同契约),包装为推送协议
请求体(scope 声明 + span kind)。标准库 urllib 同步 POST,零新依赖;
推送是只读操作——不落库、不改本地数据。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ._server.store.queries import Store
from .exporter import TraceExportError
from .recorder import Recorder

# span kind 整数值(推送协议枚举):出站依赖为 CLIENT,本地执行为 INTERNAL
_SPAN_KIND_CLIENT = 3
_SPAN_KIND_INTERNAL = 1


class PushError(Exception):
    """推送失败(端点不可达 / 非 2xx / 载荷前置校验失败)。"""


@dataclass
class PushResult:
    delivered_spans: int
    status_code: int
    endpoint: str


def push_trace(
    store: Store,
    recorder: Recorder,
    trace_id: str,
    endpoint: str,
    *,
    timeout: float = 10.0,
    branch_id: Optional[str] = None,
) -> PushResult:
    """把一条 trace 的决策链推送到收集端点,返回送达统计。失败抛 PushError,不落库。"""
    from .exporter import export_trace  # 局部导入避免环(exporter 不依赖 pusher)

    try:
        envelope = export_trace(store, recorder, trace_id, branch_id)
    except TraceExportError as e:
        raise PushError(str(e)) from e

    payload = _wrap_payload(envelope)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as e:
        snippet = ""
        try:
            snippet = e.read(200).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 读不到响应体则只报状态码
            pass
        raise PushError(f"endpoint responded {e.code}: {snippet}") from e
    except (urllib.error.URLError, OSError) as e:
        raise PushError(f"endpoint unreachable: {e}") from e

    delivered = sum(
        len(ss.get("spans") or [])
        for rs in payload["resourceSpans"]
        for ss in rs.get("scopeSpans") or []
    )
    return PushResult(delivered_spans=delivered, status_code=status_code, endpoint=endpoint)


def _wrap_payload(envelope: dict) -> dict:
    """导出信封 → 推送请求体:补 scope 声明与 span kind 字段,其余字段原样。"""
    out = {"resourceSpans": []}
    for rs in envelope.get("resourceSpans") or []:
        scope_spans = []
        for ss in rs.get("scopeSpans") or []:
            spans = []
            for span in ss.get("spans") or []:
                kind = (
                    _SPAN_KIND_CLIENT
                    if _attr_first(span, "openinference.span.kind") == "LLM"
                    else _SPAN_KIND_INTERNAL
                )
                spans.append({**span, "kind": kind})
            scope_spans.append({**ss, "scope": {"name": "agent-inspect"}, "spans": spans})
        out["resourceSpans"].append({**rs, "scopeSpans": scope_spans})
    return out


def _attr_first(span: dict, key: str) -> Optional[str]:
    for a in span.get("attributes") or []:
        if a.get("key") == key:
            v = a.get("value") or {}
            return v.get("stringValue")
    return None
