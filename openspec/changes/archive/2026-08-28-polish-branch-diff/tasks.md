# polish-branch-diff Tasks

## 1. 后端 diff 引擎修复

- [x] 1.1 `build_chain` 为每个决策点写入 `source_branch_id`
- [x] 1.2 `diff_chains` 对同源同 step 直接判 same,避免级联扩散
- [x] 1.3 更新单测:共享前缀 same、分叉后缀 diff、独立分支仍按内容比较

## 2. UI 对齐步骤列表

- [x] 2.1 新建 `BranchDiffView.jsx` 组件(行式左右卡片 + 状态色)
- [x] 2.2 `App.jsx`:选中对比分支时渲染 BranchDiffView,不再使用双 ChainCanvas
- [x] 2.3 `DiffPanel` 保持为字段明细面板,点击 diff 步骤触发
- [x] 2.4 `styles.css` 增加 BranchDiffView 样式

## 3. Demo 调整

- [x] 3.1 `react_agent_demo.py` fork 起点改为 step1,修改 step1 工具参数
- [x] 3.2 验证运行后 step0 same、step1/2 diff

## 4. 测试与验收

- [x] 4.1 更新 `tests/unit/test_diff.py`
- [x] 4.2 全量 pytest 通过(68 passed,零回归)
- [x] 4.3 `openspec validate --all` 通过
- [x] 4.4 浏览器验证新 diff 视图可读

## 5. 文档与发布

- [x] 5.1 更新 README 中分支 diff 描述(如需要)
- [x] 5.2 `openspec archive polish-branch-diff --yes`
- [x] 5.3 commit + push
