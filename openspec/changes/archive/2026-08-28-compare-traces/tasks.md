# compare-traces Tasks

## 1. 后端放宽跨 trace

- [x] 1.1 删除 `/api/branches/{a}/diff/{b}` 的 422 跨 trace 校验
- [x] 1.2 响应携带 `trace_a` / `trace_b`(agent_name,退化用 trace_id)
- [x] 1.3 新增 `/api/branches` 全局分支索引(含所属 trace 标签),供 UI 分组

## 2. UI 按 trace 分组与标注

- [x] 2.1 对比分支选择器改为全量分支按 trace 分组(组头 agent_name)
- [x] 2.2 BranchDiffView 展示左右 trace 归属标注(trace_a != trace_b 时)
- [x] 2.3 styles.css 增加 trace 徽标/optgroup 样式

## 3. Demo 与测试

- [x] 3.1 新增 `react_agent_compare_traces.py` 录制两次独立运行(不同 prompt),可跨 trace 对比
- [x] 3.2 新增跨 trace e2e(对齐步骤、仅一侧、来源标注、全局索引)
- [x] 3.3 全量 pytest 通过 + openspec validate --all 通过
- [ ] 3.4 浏览器验证跨 trace 对比可读

## 4. 文档与发布

- [ ] 4.1 README 分支 diff 描述补"跨 trace"
- [ ] 4.2 `openspec archive compare-traces --yes`
- [ ] 4.3 commit + push