"""大对象 content-addressed 去重:相同内容只存一份,决策点以引用关联。

- dev 档:序列化后超过阈值才进 blob(默认 4KB,见 contracts.md §2)。
- prod 档:一律存全文 blob + 摘要,行内只留引用标记,降低行开销。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .._server.store import queries as store_mod


class Dedup:
    def __init__(self, threshold: int = 4096) -> None:
        self.threshold = threshold

    def maybe_store(self, store: "store_mod.Store", obj: Any, record_mode: str = "dev") -> Any:
        """返回可直接落行的形态:原对象,或 {"blob_ref": hash[, summary]}。"""
        try:
            payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            payload = json.dumps(str(obj), ensure_ascii=False, sort_keys=True)

        size = len(payload.encode("utf-8"))
        if record_mode != "prod" and size <= self.threshold:
            return obj

        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        store.put_blob(f"sha256:{digest}", "json", size, payload)
        ref: dict[str, Any] = {"blob_ref": f"sha256:{digest}"}
        if record_mode == "prod":
            ref["summary"] = _summarize(payload)
        return ref


def _summarize(payload: str, limit: int = 200) -> str:
    text = payload
    return text if len(text) <= limit else text[:limit] + "...(truncated)"
