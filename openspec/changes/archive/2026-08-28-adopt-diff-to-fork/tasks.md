# adopt-diff-to-fork Tasks

## 1. 后端映射与 API

- [x] 1.1 `agent_inspect/adopt.py`:新增 `adopt_modifications(steps, right_by_step)` 纯映射(input_context 叶子/输出整段取右侧完整 output/跳过 removed)
- [x] 1.2 `_server/app.py`:新增 `POST /api/branches/{a}/diff/{b}/adopt`(校验 + dry_run 预览,404/422)

## 2. UI 采纳入口

- [x] 2.1 `api.js`:新增 `adoptDiff(a, b, payload)`
- [x] 2.2 `BranchDiffView.jsx`:diff 视图顶部「采纳差异为 Fork」入口(按 diff 处数计数,无差异禁用)
- [x] 2.3 `App.jsx`:`AdoptModal` 只读预览修改清单 → 确认 → 复用 createFork 创建,刷新分支列表并切换到新分支
- [x] 2.4 `styles.css`:采纳按钮/修改清单/弹层样式

## 3. 测试

- [x] 3.1 `tests/unit/test_adopt.py`:映射规则(input_context 叶子/output 整段/列表索引/removed 跳过/无差异) + preview 只读
- [x] 3.2 e2e:adopt preview 只读不落库 + steps 过滤 + 确认创建分支并真实执行 + 错误路径(404/422)
- [x] 3.3 全量 pytest 通过 + openspec validate --all 通过

## 4. 文档与发布

- [ ] 4.1 README 分支 diff 段补「采纳到 Fork」用法
- [ ] 4.2 `openspec archive adopt-diff-to-fork --yes`
- [ ] 4.3 commit + push
