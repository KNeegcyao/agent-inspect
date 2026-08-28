# adopt-cross-trace Design

## 概述

在 `adopt-diff-to-fork`(diff → Modification 映射)与 `compare-traces`(跨 trace diff)之上,补两块收尾:采纳预览的来源标注、fork 分支归属一致性校验,并让 UI 对跨 trace 采纳可见。两个引擎的核心语义不动。

## 1. 采纳预览来源标注

`adopt.py::preview_adopt` 目前返回 `{modifications, branch_a, branch_b, from_step, note, dry_run}`。改为返回额外两个字段(与 `diff_branches` 路由口径一致):

```
{
  ...,
  "trace_a": <branch_a 所属 trace 的 agent_name,退化用 trace_id>,
  "trace_b": <branch_b 所属 trace 的 agent_name,退化用 trace_id>,
}
```

取值:`store.get_branch(branch_a).trace_id` → `store.get_trace(...)`;无 trace 记录时回退 `trace_id` 本身。修改值来源不变:仍由 `build_chain(store, ..., branch_b)` 取对比分支(可能属另一 trace)的完整记录值。

调用方路由 `/api/branches/{a}/diff/{b}/adopt` 直接返回该结果;无需在路由层二次查询。

## 2. fork 分支归属校验

`fork.py::ForkController.request_fork` 在现有校验(空链、起点越界)之后、`create_branch` 之前,新增:

```
from_branch 必须存在(store.get_branch(from_branch) is not None)
且 from_branch.trace_id == trace_id
否则 raise ForkError("from_branch {x} does not belong to trace {t}")
```

- 现有 `/api/forks` 与采纳确认(`AdoptModal` → `createFork`)共用 `request_fork`,校验天然生效;`ForkError` 已被路由捕获并返回 422,无需改路由错误处理。
- 语义:新分支 `create_branch(trace_id, parent_branch_id=from_branch, ...)` 要求父分支与本分支同 trace,保证前缀回放(`_prefix_last_dp` / `recorded_point` 沿父链回溯)始终落在同一 trace。

## 3. UI 跨 trace 可见性

`AdoptModal`(App.jsx)从 `preview` 响应读取 `trace_a` / `trace_b`:

- 两侧分支行已显示 `branchA/branchB` 短 id,追加各自 trace 名;
- `trace_a != trace_b` 时,在修改清单上方显示警示条:「修改值取自另一条 trace(对比分支 · {trace_b})」,确认按钮文案保持「确认创建 Fork」,但用户明确看到跨 trace 语义;
- `traceData.trace.id` 仍是创建目标(主分支所在 trace),不改 `createFork` 调用参数。

## 数据流

```
跨 trace 对比视图(BranchDiffView,左=traceA/右=traceB)
  → AdoptModal:
      POST /api/branches/{A}/diff/{B}/adopt {from_step}   (只读预览)
        → preview_adopt → {modifications, trace_a, trace_b, dry_run}
      UI 展示两侧 trace + (跨 trace 警示条) + 修改清单
  → 确认 → POST /api/forks {trace_id: traceA, branch_id: A, from_step, modifications}
        → request_fork:空链 / 越界 / 归属一致(新增)→ 创建新分支于 traceA
  → 执行:前缀回放 + 后缀真调(采纳的 output 覆盖不真调)
```

## 文件改动

- `agent_inspect/adopt.py`:`preview_adopt` 追加 `trace_a` / `trace_b`。
- `agent_inspect/fork.py`:`request_fork` 追加父分支归属校验。
- `web/src/App.jsx`:`AdoptModal` 展示 trace 归属 + 跨 trace 警示条。
- `web/src/styles.css`:跨 trace 警示条样式(复用现有警示风格)。
- `tests/unit/test_adopt.py`:跨 trace 预览来源标注单测。
- `tests/unit/test_fork.py`:分支归属校验单测。
- `tests/integration/test_server_e2e.py`:跨 trace 采纳端到端。
