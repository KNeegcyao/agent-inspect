# delete-traces Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:删除的 why / 级联语义 / blob 不清理的理由
- [x] 1.2 `specs/recording/spec.md` delta:「trace 删除管理」1 requirement 共 3 场景

## 2. 后端

- [x] 2.1 store.delete_trace:级联(decision_points / context_diffs / branches / breakpoints / traces),blob 不动;单测(级联完整 + 隔离 + 不存在 False)
- [x] 2.2 `DELETE /api/traces/{trace_id}`:200/404;SSE `trace.deleted` 事件

## 3. UI

- [x] 3.1 api.js `deleteTrace`;App.jsx 列表项删除入口(confirm → 删除 → 刷新;删当前选中回空态;SSE trace.deleted 触发刷新)
- [x] 3.2 危险色删除按钮样式

## 4. 测试与回归

- [x] 4.1 e2e:两条 trace → 删第一条 → 列表/详情/points 全部符合预期;重复删 404
- [x] 4.2 全量 pytest 通过,零回归

## 5. 验证与发布

- [x] 5.1 `openspec validate --all` 通过;`npm run build` 通过
- [x] 5.2 README(如涉及用户可见行为变更,补一句);`openspec/archive delete-traces`;commit + push
