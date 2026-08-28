# compare-traces Design

## Backend (app.py)

`/api/branches/{branch_a}/diff/{branch_b}`:

- 删除 422 跨 trace 校验,仅保留 404(分支不存在)。
- 补齐响应头:
  ```python
  tra = session.store.get_trace(ba.trace_id)
  trb = session.store.get_trace(bb.trace_id)
  result = diff_branches(...)
  result["trace_a"] = tra.agent_name if tra else ba.trace_id
  result["trace_b"] = trb.agent_name if trb else bb.trace_id
  return result
  ```

`diff_branches`(diff.py)无需改动——cross-trace 的两个分支 id 必然不同,`diff_chains` 走内容比较分支。

## Frontend (App.jsx)

- 对比分支选择器的候选项,**不再按当前 trace 过滤**,改为 `listBranches()` 全量;渲染时按 `Trace.id` 分组,组头显示 `trace.agent_name`。
- `diffData` 增加 `trace_a` / `trace_b`;当两者不同时,BranchDiffView 顶部或分支标签显示 `agent_name` 以标注归属。
- 分支下拉当前的"对比分支"若跨 trace,主分支标签照旧显示自身 agent_name。

## Styling (styles.css)

- 分支下拉分组(optgroup)样式;跨 trace 时 diff 视图标题附加 trace 徽标。

## Demo

`examples/react_agent_demo.py` 追加第二次独立运行:
- trace1:`1 + 2` → 答案 3(执行 `graph1`)。
- trace2:`3 x 4` → 答案 12(执行 `graph2`,不同 prompt)。

面板选择 trace1.root 与 trace2.root 对比,可见步骤数相同、内容不同 → 全 diff。