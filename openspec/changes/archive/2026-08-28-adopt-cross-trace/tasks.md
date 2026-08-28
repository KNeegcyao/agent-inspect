# adopt-cross-trace Tasks

## 1. 后端:采纳预览来源标注

- [x] 1.1 `preview_adopt` 追加 `trace_a` / `trace_b`(agent_name,退化用 trace_id)
- [x] 1.2 `/api/branches/{a}/diff/{b}/adopt` 返回含 trace 标注(直接透传 preview 结果)

## 2. 后端:fork 分支归属校验

- [x] 2.1 `request_fork` 校验 `from_branch` 存在且 `from_branch.trace_id == trace_id`,不一致 `ForkError`(422,不落库)
- [x] 2.2 确认现有 `/api/forks` 与采纳确认共用该校验,无需改路由错误处理

## 3. UI:跨 trace 可见性

- [x] 3.1 AdoptModal 从 preview 读 `trace_a`/`trace_b`,两侧分支行显示 trace 归属
- [x] 3.2 `trace_a != trace_b` 时显示跨 trace 警示条(修改值来自另一 trace)
- [x] 3.3 styles.css 增加跨 trace 警示条样式

## 4. 测试

- [x] 4.1 单元:跨 trace 采纳预览来源标注 + 值取自另一 trace
- [x] 4.2 单元:fork 分支归属校验(父分支不在目标 trace → 拒绝)
- [x] 4.3 e2e:两条 trace → 跨 trace 采纳预览(带标注)→ 确认创建于主 trace → 执行后采纳值生效、输出覆盖不真调
- [x] 4.4 全量 pytest 通过 + `openspec validate --all` 通过 + vite build 通过

## 5. 文档与发布

- [x] 5.1 README 采纳段落补"跨 trace"来源标注
- [x] 5.2 `openspec archive adopt-cross-trace --yes`
- [x] 5.3 commit + push
