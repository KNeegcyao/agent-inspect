# polish-branch-diff Design

## Backend

### Source branch identity in chain

`build_chain` 在解析每个决策点时,额外写入 `source_branch_id`:

```python
resolved = serializer.resolve_dp(store, p, context_snap)
resolved["source_branch_id"] = branch_id
resolved["inherited"] = inherited
```

前缀步骤使用父分支的 `branch_id`,后缀步骤使用本分支的 `branch_id`。

### Short-circuit in diff_chains

```python
if a.get("source_branch_id") and a.get("source_branch_id") == b.get("source_branch_id"):
    status = STEP_SAME
    fields = []
else:
    # 原有比较逻辑
```

这样,父分支 step0 与 fork 分支继承来的 step0 来源分支相同,直接判 same;真正 fork 出去的后缀来源分支不同,才比较内容。

## Frontend

### BranchDiffView 组件

路径:`web/src/components/BranchDiffView.jsx`

Props:
- `activeChain`
- `compareChain`
- `diffData`
- `selectedId`
- `onSelect(stepIndex, pointId)`
- `activeBranchId`
- `compareBranchId`

行为:
1. 以 `diffData.steps` 为顺序渲染每行。
2. 每行包含:
   - 步骤序号 `step_index`
   - 左侧卡片:主分支该 step 的 point(若存在),显示 kind + agent_id + output 摘要
   - 右侧卡片:对比分支该 step 的 point(若存在)
   - 状态标签:same/diff/only_left/only_right
3. 卡片点击调用 `onSelect(point.id)`,让 App.jsx 在右侧面板展示 `DiffPanel`。

### App.jsx 集成

当 `compareBranchId` 存在时,不再渲染双 `ChainCanvas`,而是渲染:

```jsx
<BranchDiffView
  activeChain={activeChain}
  compareChain={compareChain}
  diffData={diffData}
  selectedId={selectedId}
  onSelect={(stepIndex, pointId) => setSelectedId(pointId)}
  activeBranchId={activeBranchId}
  compareBranchId={compareBranchId}
/>
```

选中逻辑保持:点击差异步骤选中,`DiffPanel` 显示字段明细。

### Styling

- `.branch-diff-view`:flex column, gap 10px, padding 10px, overflow auto
- `.diff-step-row`:grid `40px 1fr 1fr`, align center
- `.diff-step-card`:border, radius 8px, padding 10px, font-size 12px
- 状态色:same 默认边框,diff 玫瑰红,only_left 琥珀,only_right 蓝色
- `.diff-step-output`:monospace, max-height 80px, overflow auto

## Demo

`examples/react_agent_demo.py` 中:
- fork 起点从 `from_step=0` 改为 `from_step=1`
- 修改 step1 的工具调用参数:`add(x=1, y=2)` → `add(x=4, y=5)`
- 第二组 scripted 响应对应返回 `4 + 5 = 9`

效果:step0(prompt) 共享且相同;step1 工具调用参数不同 → diff;step2 最终答案不同 → diff。
