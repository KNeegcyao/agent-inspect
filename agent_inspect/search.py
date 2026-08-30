"""决策点内容搜索:单 trace 全分支按子串(大小写不敏感)检索输入/输出。

只读计算:经既有解析层(read_branch_points,含 diff/blob 还原)取完整内容,
序列化后线性匹配;本地单文件规模无索引。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ._server.store.queries import Store
from .recorder import Recorder

SNIPPET_RADIUS = 60


class SearchError(ValueError):
    """搜索参数非法(缺查询串)。"""


def search_trace(store: Store, recorder: Recorder, trace_id: str, query: str) -> list[dict]:
    """在 trace 全部分支内搜索输入/输出包含 query(忽略大小写)的决策点。

    返回按 (分支插入序, step_index, 输入优先) 排序的命中列表:
    {branch_id, step_index, kind, agent_id, matched_in: "input"|"output", snippet}
    """
    needle = query.lower()
    matches: list[dict] = []
    for branch in store.list_branches(trace_id):
        for p in recorder.read_branch_points(trace_id, branch.id):
            for where, content in (
                ("input", p["input_context"]),
                ("output", p["output"]),
            ):
                if content is None:
                    continue
                text = json.dumps(content, ensure_ascii=False, default=str).lower()
                pos = text.find(needle)
                if pos >= 0:
                    matches.append(
                        {
                            "branch_id": branch.id,
                            "step_index": p["step_index"],
                            "kind": p["kind"],
                            "agent_id": p["agent_id"],
                            "dp_id": p["id"],
                            "matched_in": where,
                            "snippet": _snippet(text, pos, len(needle)),
                        }
                    )
    order = {b.id: i for i, b in enumerate(store.list_branches(trace_id))}
    matches.sort(
        key=lambda m: (
            order.get(m["branch_id"], 1 << 30),
            m["step_index"],
            0 if m["matched_in"] == "input" else 1,
        )
    )
    return matches


def _snippet(text: str, pos: int, needle_len: int) -> str:
    start = max(0, pos - SNIPPET_RADIUS)
    end = min(len(text), pos + needle_len + SNIPPET_RADIUS)
    raw = text[start:end]
    return " ".join(raw.split())  # 压行:换行/多空白归一
