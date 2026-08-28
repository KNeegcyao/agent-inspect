# compare-traces

## Why

`branch-diff` 目前只能比较**同一 trace** 内的两条分支(跨 trace 直接返回 422)。但在调试中,"同 agent 换 prompt / 换模型 / 换版本跑两次,比较两条完整执行"，是比"同 trace 内分叉"更常见的需求。当前 diff 引擎(`build_chain` + `diff_chains`)本身不依赖 trace 边界,天然支持跨 trace,却被人为的 422 档住了。本 change 打开这条能力:把两条不同运行也纳入并排对比,并按 trace 分组选择。

## Scope

- 后端:`/api/branches/{a}/diff/{b}` 去掉"必须同 trace"的限制;响应附带左右 trace 的 agent_name,供 UI 标签。
- UI:对比分支下拉支持跨 trace(按 trace 分组带 agent_name);diff 视图标题显示两个 trace 的归属。
- 单测:跨 trace 对齐步骤、跨 trace 标签返回。

## Out of scope

- 跨 trace 分叉/采纳(diff → fork 应用),后续 change。
- 三向合并、历史版本 diff。

## What Changes

- 后端放宽跨 trace:`/api/branches/{a}/diff/{b}` 不再要求同 trace(删除 422),响应携带 `trace_a` / `trace_b`(agent_name,退化用 trace_id);新增 `/api/branches` 全局分支索引,返回所有 trace 的分支并附所属 trace 标签,供 UI 分组。
- UI:对比分支下拉改为全量分支按 trace 分组(组头 agent_name,含跨 trace 选项);BranchDiffView 标题在两侧分支归属不同 trace 时标注各自 agent 名并附分支短 id;新增 trace 徽标/optgroup 样式。
- Demo/测试:新增 `examples/react_agent_compare_traces.py` 录制两次独立运行(不同 prompt)演示跨 trace 对比;e2e 增加跨 trace 对齐、仅一侧、来源标注与全局分支索引断言。