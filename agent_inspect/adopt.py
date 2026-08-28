"""采纳映射:把分支 diff 的字段级差异转换为 Fork 修改(Modification)。

设计(change `adopt-diff-to-fork`):
- 输入区叶子差异(`input_context.*`)→ 独立 `input_context.<path>` 修改,注入后真调;
- 输出区差异(`output` 或 `output.*`)→ 整段 `output` 覆盖(与 fork 修改语义一致);
- `removed`(仅左侧有,右侧无值可采纳)→ 跳过;
- 无差异/同步骤 same → 不生成。

纯函数,不触碰存储与执行;由 API 路由在 diff 结果之上调用。
"""
from __future__ import annotations

from typing import Any, Optional

from .fork import Modification

# diff.py 字段级状态
FIELD_ADDED = "added"
FIELD_REMOVED = "removed"
FIELD_CHANGED = "changed"


def adopt_modifications(
    steps: list[dict],
    right_by_step: Optional[dict[int, dict]] = None,
) -> list[Modification]:
    """把 diff steps(含 fields)映射为一组采纳修改。

    每个 diff 步骤:
    - 输入区(`input_context.*`)逐叶子路径生成一条修改(value=右侧叶子值);
    - 输出区(`output`/`output.*`)合并为一条整段 output 覆盖(value=右侧完整 output,
      由 right_by_step[step]["output"] 提供;缺省时退化为字段右值);
    - `removed` 字段跳过。
    非 diff / same / only 步骤无 fields,自然跳过。
    """
    out: list[Modification] = []
    for s in steps:
        if s.get("status") != "diff":
            continue
        step = int(s["step_index"])
        for f in s.get("fields", []):
            if f.get("status") == FIELD_REMOVED:
                continue
            path = f.get("path", "")
            if path == "output" or path.startswith("output."):
                # 输出区差异合并为整段覆盖(值取右侧完整 output)
                if not any(m.step == step and m.field == "output" for m in out):
                    value = f.get("right")
                    if right_by_step is not None:
                        rp = right_by_step.get(step)
                        if rp is not None and rp.get("output") is not None:
                            value = rp.get("output")
                    out.append(Modification(step=step, field="output", value=value))
            elif path.startswith("input_context.") or path.startswith("input_context["):
                if f.get("right") is not None or f.get("status") == FIELD_ADDED:
                    out.append(Modification(step=step, field=path, value=f.get("right")))
    # 稳定排序:先按步骤,同步骤输出覆盖在前
    out.sort(key=lambda m: (m.step, 0 if m.field == "output" else 1))
    return out


def preview_adopt(
    store,
    serializer,
    context_snap,
    branch_a: str,
    branch_b: str,
    from_step: int,
    steps: Optional[list[int]] = None,
    note: Optional[str] = None,
):
    """由两分支 diff 计算采纳修改,并校验可发起 Fork(dry_run),返回可执行预览。

    只读:不创建分支、不发真实调用。校验空链/起点越界由调用方(request_fork dry_run)兜底。
    返回 {modifications, branch_a, branch_b, from_step, note, dry_run: True, plan,
          trace_a, trace_b, trace_id_a, trace_id_b}。trace_a / trace_b 为两侧分支所属 trace 的
    agent_name(退化用 trace_id);trace_id_a / trace_id_b 为对应 trace id,供 UI 判定跨 trace。
    """
    from .diff import build_chain, diff_branches

    result = diff_branches(store, serializer, context_snap, branch_a, branch_b)
    diff_steps = result["steps"]
    if steps is not None:
        want = set(int(x) for x in steps)
        diff_steps = [s for s in diff_steps if int(s["step_index"]) in want]
    # 输出整段覆盖需要右侧完整 output:单独构建右侧链路,按 step_index 索引
    right_chain = build_chain(store, serializer, context_snap, branch_b)
    right_by_step = {p["step_index"]: p for p in right_chain}
    mods = adopt_modifications(diff_steps, right_by_step=right_by_step)
    return {
        "modifications": [m.to_dict() for m in mods],
        "branch_a": branch_a,
        "branch_b": branch_b,
        "from_step": from_step,
        "note": note,
        "dry_run": True,
        "trace_a": _trace_label(store, branch_a),
        "trace_b": _trace_label(store, branch_b),
        "trace_id_a": _trace_id(store, branch_a),
        "trace_id_b": _trace_id(store, branch_b),
    }


def _trace_label(store, branch_id: str) -> str:
    """分支所属 trace 的 agent_name,缺失时回退 trace_id。"""
    branch = store.get_branch(branch_id)
    if branch is None:
        return ""
    t = store.get_trace(branch.trace_id)
    return t.agent_name if t else branch.trace_id


def _trace_id(store, branch_id: str) -> str:
    branch = store.get_branch(branch_id)
    return branch.trace_id if branch is not None else ""