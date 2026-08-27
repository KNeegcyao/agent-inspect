"""增量上下文快照:共享前缀只存一份,单点回放仍能重建全量。

方案:每条分支首条决策点存全量快照(diff_against_step=None),其后各条存相对前序的
JSON-pointer 风格 diff。重建时从快照起依序应用 diff。进程内维护 (branch, step)->full 缓存
避免录制时反复回扫 DB。
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from .._models import new_id


class ContextSnap:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], Any] = {}

    # ---- record ----
    def record(self, store, dp) -> None:
        branch_id, step = dp.branch_id, dp.step_index
        prev_step = store.last_step_before(branch_id, step)
        if prev_step is None:
            payload = copy.deepcopy(dp.input_context)
            against: Optional[int] = None
        else:
            prev_full = self._full(store, branch_id, prev_step)
            payload = diff(prev_full, dp.input_context)
            against = prev_step
        diff_id = new_id("ctx")
        store.write_context_diff(diff_id, branch_id, step, against, payload)
        self._cache[(branch_id, step)] = copy.deepcopy(dp.input_context)
        # 替换为引用,行内不再存全量上下文
        dp.input_context = {"context_diff_ref": diff_id}

    def _full(self, store, branch_id: str, step: int) -> Any:
        cached = self._cache.get((branch_id, step))
        if cached is not None:
            return cached
        return self.reconstruct(store, branch_id, step)

    # ---- reconstruct ----
    def reconstruct(self, store, branch_id: str, step_index: int) -> Any:
        rows = store.get_context_diffs(branch_id, step_index)
        base: Optional[Any] = None
        ops: list[tuple[int, Any]] = []
        for step, against, payload in rows:
            if against is None:
                if base is None:
                    base = copy.deepcopy(payload)
            else:
                ops.append((step, payload))
        if base is None:
            return {}
        for step, payload in sorted(ops, key=lambda x: x[0]):
            if step <= step_index:
                apply_ops(base, payload)
        return base


# ---- 递归 diff / apply ----
def diff(base: Any, target: Any) -> list[dict]:
    ops: list[dict] = []
    _diff(base, target, ops, [])
    return ops


def _diff(a: Any, b: Any, ops: list[dict], path: list) -> None:
    if type(a) is not type(b):
        ops.append({"op": "replace", "path": list(path), "value": copy.deepcopy(b)})
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a.keys()) - set(b.keys())):
            ops.append({"op": "remove", "path": path + [k]})
        for k in sorted(b.keys()):
            if k not in a:
                ops.append({"op": "add", "path": path + [k], "value": copy.deepcopy(b[k])})
            elif a[k] != b[k]:
                _diff(a[k], b[k], ops, path + [k])
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            if i >= len(a):
                ops.append({"op": "add", "path": path + [i], "value": copy.deepcopy(b[i])})
            elif i >= len(b):
                ops.append({"op": "remove", "path": path + [i]})
            elif a[i] != b[i]:
                _diff(a[i], b[i], ops, path + [i])
    elif a != b:
        ops.append({"op": "replace", "path": list(path), "value": copy.deepcopy(b)})


def apply_ops(obj: Any, ops: list[dict]) -> None:
    for op in ops:
        _apply(obj, op)


def _apply(obj: Any, op: dict) -> None:
    path = op.get("path") or []
    if not path:
        obj = op["value"]
        return
    target = obj
    for p in path[:-1]:
        if isinstance(target, list):
            while len(target) <= p:
                target.append(None)
        target = target[p]
    key = path[-1]
    if op["op"] == "remove":
        if isinstance(target, list):
            if len(target) > key:
                del target[key]
        else:
            target.pop(key, None)
    else:  # add / replace
        if isinstance(target, list):
            while len(target) <= key:
                target.append(None)
            target[key] = op["value"]
        else:
            target[key] = op["value"]
