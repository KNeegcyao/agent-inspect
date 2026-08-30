# global-search Tasks

## 1. OpenSpec 文档

- [ ] 1.1 `proposal.md` / `design.md`:全局搜索的 why / 分组语义 / 每组截断策略
- [ ] 1.2 `specs/trace-search/spec.md` delta:「跨 trace 全局搜索」+「面板全局搜索入口」2 requirement 共 5 场景

## 2. 后端

- [ ] 2.1 `GET /api/search?q=`:遍历全部 trace 分组检索(每组截前 50、合计完整);缺 q 422;e2e

## 3. UI

- [ ] 3.1 侧栏全局搜索框(防抖)+ 分组命中视图(trace 头 / 命中直达 / 清空恢复);样式
- [ ] 3.2 浏览器实测:分组结果、直达定位、清空恢复

## 4. 验证与发布

- [ ] 4.1 全量 pytest 零回归;`npm run build` 通过;`openspec validate --all` 通过
- [ ] 4.2 README 补全局搜索;`openspec/archive global-search`;commit + push
