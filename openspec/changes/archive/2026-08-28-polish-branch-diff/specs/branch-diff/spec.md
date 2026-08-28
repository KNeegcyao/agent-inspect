# branch-diff Specification

## Purpose

改进分支并排 diff 的语义与渲染:让共同祖先上的共享前缀正确判定为 same,并提供更易读的对齐步骤列表视图。

## ADDED Requirements

### Requirement: 共享前缀应判定为 same

系统 SHALL 在比较两条分支时,把来自共同祖先的同一决策点判定为 same,而不是因为后续输入上下文被连带修改就标为 diff。

#### Scenario: 祖先前缀标为 same

- **WHEN** 比较一条父分支与从其 step1 分出的 fork 分支
- **THEN** step0 显示为 same(左右来自同一来源分支的同一步骤)

#### Scenario: 分叉后缀才标为 diff

- **WHEN** 比较父分支与 fork 分支
- **THEN** 只有 fork 点开始(step1 及之后)的步骤才参与内容比较并可能标为 diff

#### Scenario: 独立分支仍按内容比较

- **WHEN** 比较两条没有继承关系的分支(如两条都独立的 root 分支)
- **THEN** 按 kind/output/input_context 内容比较,不短路

### Requirement: 对齐步骤列表视图

系统 SHALL 在选中对比分支后,以按 step_index 对齐的垂直列表展示每个步骤,左右两侧分别显示主分支与对比分支的决策点摘要。

#### Scenario: 每行展示左右决策点

- **WHEN** 用户在 diff 视图中查看某一步
- **THEN** 该行左侧显示主分支该 step 的 kind/output 摘要,右侧显示对比分支对应摘要

#### Scenario: 仅一侧存在步骤

- **WHEN** 某 step_index 只存在于一个分支
- **THEN** 另一侧显示空白占位,并标为 only_left / only_right

#### Scenario: 差异步骤高亮

- **WHEN** 某步骤状态为 diff
- **THEN** 该行边框或背景使用差异色,提示用户可点击展开字段明细

#### Scenario: 点击差异步骤查看字段明细

- **WHEN** 用户点击一个 diff 步骤
- **THEN** 右侧面板显示该步骤 input_context + output 的字段级 diff

## DECISIONS

- 用「来源分支 + step_index」作为记录身份标识,相同即 same;避免逐字段比较导致的级联扩散。
- 不修改 ChainCanvas,而是新增专用 BranchDiffView 组件,降低对现有链式可视化的影响。