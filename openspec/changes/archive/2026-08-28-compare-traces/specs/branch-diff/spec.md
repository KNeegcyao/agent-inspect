# branch-diff Specification

## Purpose

把分支并排 diff 扩展到**跨 trace**:允许比较两条不同的执行记录,并在 UI 中按 trace 分组选择与标注。

## ADDED Requirements

### Requirement: 跨 trace 对比

系统 SHALL 允许对两条来自不同 trace 的分支执行并排 diff,并按 step_index 对齐其决策点。

#### Scenario: 不同 trace 可对比

- **WHEN** 用户选择两条分别属于不同 trace 的分支进行对比
- **THEN** 系统返回对齐后的步骤列表(含 same/diff/only_left/only_right)与字段级明细,不因 trace 不同而拒绝

#### Scenario: 仅一侧存在步骤

- **WHEN** 两条 trace 的步骤数不同
- **THEN** 多余步骤标记为 only_left / only_right,另一侧显示空白占位

#### Scenario: 不同 trace 共享前缀不被误判

- **WHEN** 两条 trace 的步骤来源互不相同
- **THEN** 即使步骤输出看起来相同,也不因"来源分支相同"而短路;完全按内容比较

#### Scenario: 对比选择按 trace 分组

- **WHEN** 用户在 UI 选择对比分支
- **THEN** 候选分支按所属 trace 分组展示,并标注每个 trace 的 agent_name

#### Scenario: 视图标注两侧来源

- **WHEN** 跨 trace 对比结果展示时
- **THEN** 视图像主导航标题中标注左右两侧各自的 trace 归属

## DECISIONS

- 复用既有 `diff_chains`:其来源分支短路判定仅在左右来源分支 id 相同时生效;跨 trace 两个分支 id 必不同,自然落到"按内容比较"分支,无需改 diff 引擎本身。
- UI 的选择器从"同 trace 分支"放宽为"所有分支按 trace 分组",最小改动并保留可读性。