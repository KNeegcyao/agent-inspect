# trace-stats-summary Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:统计摘要的 why / 聚合语义 / 范围
- [x] 1.2 `specs/trace-ui/spec.md` delta:「运行统计摘要」1 requirement 共 3 场景

## 2. 实现

- [x] 2.1 `chain.js` 纯函数 `summarizeChain`(耗时/token 分别判定,usage 优先、meta 回退)
- [x] 2.2 `App.jsx` rel-bar 统计 chips(无数据不渲染;单位自适应)

## 3. 验证与发布

- [x] 3.1 `npm run build` 通过;全量 pytest 零回归
- [x] 3.2 浏览器实测:带 usage 的链(Σ tokens + Σ 耗时)/ 无 usage 的链(仅耗时)
- [x] 3.3 `openspec validate --all` 通过;`openspec archive trace-stats-summary`;commit + push
