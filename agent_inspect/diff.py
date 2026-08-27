"""分支并排 diff:完整链路构造、步骤对齐、字段级差异、汇总。纯只读计算,不落库。"""
from __future__ import annotations

from typing import Any, Optional

STEP_SAME = "same"
STEP_DIFF = "diff"
STEP_ONLY_LEFT = "only_left"
STEP_ONLY_RIGHT = "only_right"

FIELD_ADDED = "added"  # 仅右侧有该字段
FIELD_REMOVED = "removed"  # 仅左侧有该字段
FIELD_CHANGED = "changed"  # 两侧取值不同

# 字段级 diff 递归深度上限,避免超大 prompt 递归爆炸;超深退化为"值不同"。
MAX_FIELD_DEPTH = 6

BIG = (1 << 63) - 1


# ---- 完整链路构造(镜像 web/src/chain.js 的 chainSteps)----
def build_chain(store, serializer, context_snap, branch_id: str, upto: int = BIG) -> list[dict]:
    """完整决策链:共享前缀(继承自父分支)+ 本分支后缀。

    Fork 分支只记录 branch_from_step 之后的决策点,前缀步骤存于父分支;
    沿 parent_branch_id 递归回溯拼出完整链,并标记 inherited(共享前缀)。
    """
    return _chain_steps(store, serializer, context_snap, branch_id, upto, inherited=False)


def _chain_steps(store, serializer, context_snap, branch_id: str, upto: int, inherited: bool) -> list[dict]:
    if upto <= 0:
        return []
    branch = store.get_branch(branch_id)
    if branch is None:
        return []
    own = []
    for p in store.get_decision_points(branch.trace_id, branch_id):
        if p.step_index >= upto:
            break
        resolved = serializer.resolve_dp(store, p, context_snap)
        resolved["inherited"] = inherited
        own.append(resolved)
    parent = branch.parent_branch_id
    if parent is not None:
        need = min(branch.branch_from_step, upto)
        if need > 0:
            prefix = _chain_steps(store, serializer, context_snap, parent, need, True)
            return prefix + own
    return own


# ---- 步骤对齐 ----
def diff_chains(left: list[dict], right: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """按 step_index 对齐两链,返回 (steps, summary)。

    steps 每项:{step_index, status, kind?, agent_id?, fields?}
    - status ∈ same / diff / only_left / only_right
    - diff 步骤附 fields:输入(input_context)与输出(output)两段的字段级差异
    """
    by_left = {p["step_index"]: p for p in left}
    by_right = {p["step_index"]: p for p in right}
    steps: list[dict] = []
    counts = {STEP_SAME: 0, STEP_DIFF: 0, STEP_ONLY_LEFT: 0, STEP_ONLY_RIGHT: 0}
    for idx in sorted(set(by_left) | set(by_right)):
        a = by_left.get(idx)
        b = by_right.get(idx)
        if a is None:
            steps.append(_step(idx, STEP_ONLY_RIGHT, None, b))
            counts[STEP_ONLY_RIGHT] += 1
        elif b is None:
            steps.append(_step(idx, STEP_ONLY_LEFT, a, None))
            counts[STEP_ONLY_LEFT] += 1
        else:
            differs = (
                a.get("kind") != b.get("kind")
                or _json_cmp(a.get("output"), b.get("output")) != 0
                or _json_cmp(a.get("input_context"), b.get("input_context")) != 0
            )
            status = STEP_DIFF if differs else STEP_SAME
            fields = diff_fields(a, b) if differs else []
            steps.append(_step(idx, status, a, b, fields))
            counts[status] += 1
    return steps, counts


def _step(step_index: int, status: str, a: Optional[dict], b: Optional[dict], fields: Optional[list] = None) -> dict:
    base: dict[str, Any] = {"step_index": step_index, "status": status}
    side = a if a is not None else b
    if side is not None:
        base["kind"] = side.get("kind")
        base["agent_id"] = side.get("agent_id")
    if fields:
        base["fields"] = fields
    return base


# ---- 字段级差异 ----
def diff_fields(a: dict, b: dict) -> list[dict]:
    """输入与输出两段的字段级差异(叶子路径,深度受限)。"""
    out: list[dict] = []
    for section in ("input_context", "output"):
        va = a.get(section)
        vb = b.get(section)
        if _json_cmp(va, vb) != 0:
            _walk(va, vb, section, 0, out)
    return out


def _walk(va: Any, vb: Any, path: str, depth: int, out: list[dict]) -> None:
    if depth > MAX_FIELD_DEPTH:
        out.append({"path": path, "left": va, "right": vb, "status": FIELD_CHANGED})
        return
    if isinstance(va, dict) and isinstance(vb, dict):
        for k in sorted(set(va) | set(vb)):
            child = f"{path}.{k}"
            if k in va and k in vb:
                _walk(va[k], vb[k], child, depth + 1, out)
            elif k in va:
                out.append({"path": child, "left": va[k], "right": None, "status": FIELD_REMOVED})
            else:
                out.append({"path": child, "left": None, "right": vb[k], "status": FIELD_ADDED})
        return
    if isinstance(va, list) and isinstance(vb, list):
        n = max(len(va), len(vb))
        for i in range(n):
            child = f"{path}[{i}]"
            if i < len(va) and i < len(vb):
                _walk(va[i], vb[i], child, depth + 1, out)
            elif i < len(va):
                out.append({"path": child, "left": va[i], "right": None, "status": FIELD_REMOVED})
            else:
                out.append({"path": child, "left": None, "right": vb[i], "status": FIELD_ADDED})
        return
    if _json_cmp(va, vb) != 0:
        out.append({"path": path, "left": va, "right": vb, "status": FIELD_CHANGED})


# ---- 汇总与入口 ----
def diff_branches(store, serializer, context_snap, branch_a: str, branch_b: str) -> dict:
    """两分支完整链路 diff,返回面板直接可用的结构。"""
    left = build_chain(store, serializer, context_snap, branch_a)
    right = build_chain(store, serializer, context_snap, branch_b)
    steps, counts = diff_chains(left, right)
    return {
        "branch_a": branch_a,
        "branch_b": branch_b,
        "steps": steps,
        "summary": counts,
    }


def _json_cmp(a: Any, b: Any) -> int:
    """结构化相等(含 None 与 dict/list);相等返回 0,否则 1。"""
    return 0 if a == b else 1
