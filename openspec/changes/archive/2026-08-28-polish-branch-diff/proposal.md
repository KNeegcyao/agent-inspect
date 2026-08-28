# polish-branch-diff

## Why

`add-branch-diff` 已交付后端 diff 引擎、只读接口与基础并排视图,但在真实 demo 中暴露两个体验问题:

1. **diff 语义错误地把「共享前缀」标成 diff**。Fork 修改了早期 step 的 prompt 后,后续 step 的 `input_context.messages` 会携带新 prompt,导致引擎把后续所有步骤判为 diff。用户期望的是:只要两个分支在共同祖先上的同一步骤是**同一条记录**,就应标为 same,只有真正分叉后的步骤才需要比较。
2. **并排视图使用两个 ChainCanvas,布局难用**。节点被撑到列宽(半屏),JSON 输出折行、标题被挤出可视区,字段差异面板也没合适位置展示。

本 change 修复引擎的级联扩散问题,并用一个专门的「对齐步骤列表」组件替换双 ChainCanvas,使分支 diff 真正可用。

## Scope

- 后端:为完整链中的每个决策点标记来源分支,`diff_chains` 对同源同步骤直接判 same。
- UI:新增 `BranchDiffView` 组件,按 step_index 渲染每行的左右小卡片;保留字段级 `DiffPanel`。
- Demo:把 fork 起点从 step0 改为 step1,让 step0 成为共享前缀(step0 same, step1/2 diff)。
- 更新 diff 单测,保证共享前缀判定正确。

## What Changes

- `agent_inspect/diff.py`:`build_chain` 为每个决策点写入 `source_branch_id`;`diff_chains` 对同源同 step 直接判 same,消除输入上下文级联扩散。
- 新增 `web/src/components/BranchDiffView.jsx`:按 step_index 对齐的左右卡片列表,展示 same/diff/only_left/only_right 与状态高亮;取代 diff 模式下的双 ChainCanvas。
- `web/src/App.jsx` + `styles.css`:选中对比分支时渲染 BranchDiffView,点击 diff 步骤展示字段明细 DiffPanel。
- `examples/react_agent_demo.py`:fork 起点改为 step1,展示「共享前缀 same + 分叉后缀 diff」。
- `tests/unit/test_diff.py`:新增同源短路、不同源内容比较、source_branch_id 标记等用例。

## Out of scope

- 三向合并、跨 trace diff、diff 历史版本。
- 改动现有 ChainCanvas 在非 diff 模式下的行为。
