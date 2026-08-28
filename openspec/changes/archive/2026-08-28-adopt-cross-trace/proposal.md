# adopt-cross-trace

## Why

`compare-traces` 已能跨 trace 并排 diff,`adopt-diff-to-fork` 已能把同一 trace 内的 diff 差异一键采纳为 Fork 修改。但两者焊接点仍缺一环:**跨 trace 采纳**——当对比分支属于另一条运行(trace)时,采纳值取自那一次运行,而目标分支属于当前 trace。

现状:
- diff 预览接口(`/adopt`)本身不拒绝跨 trace,但响应**不含两侧 trace 归属**;用户无法在 UI 上确认"修改值来自另一条 trace",跨 trace 采纳与同 trace 采纳在界面上无差别,容易误操作。
- 采纳确认走 `/api/forks` 创建分支时,**不校验 `from_branch` 是否真的属于 `trace_id`**。跨 trace 采纳放大了这个隐患:一旦前端传错 trace_id,会落库一条"父分支在 trace B、声明归属 trace A"的错位分支,前缀回放与后续查询都会错乱。
- 跨 trace 采纳没有任何单元 / e2e 测试覆盖,行为停留在"碰巧能用"。

本 change 把跨 trace 采纳做成**一等公民**:采纳预览带两侧 trace 来源标注(可观测),创建分支前校验分支归属一致性(防错位),并以端到端测试锁死「另一条 trace 的值 → 当前 trace 的新分支」这条链路。

## What Changes

- **后端(采纳预览来源标注)**:`preview_adopt` 结果携带 `trace_a` / `trace_b`(agent_name,退化用 trace_id),与 diff 接口口径一致;采纳修改值仍取对比分支所在 trace 的记录值。
- **后端(分支归属校验)**:`ForkController.request_fork` 校验 `from_branch` 存在且其所属 trace 与 `trace_id` 一致,不一致以可观测原因拒绝(422),不落库;现有 `/api/forks` 与采纳确认共用此校验。
- **UI(跨 trace 可见性)**:AdoptModal 展示两侧分支的 trace 归属;当两侧 trace 不同时,明确提示"修改值取自另一条 trace(对比分支)",确认文案区分同 trace / 跨 trace。
- **测试**:
  - 单元:跨 trace 采纳预览的来源标注与值来源(另一 trace 的记录值);fork 分支归属校验(父分支不在目标 trace → 拒绝)。
  - e2e:两条 trace → 跨 trace 采纳预览(带 trace 标注)→ 确认创建于主 trace → 执行后采纳值生效、输出覆盖不真调。

## Out of scope

- 跨 trace 采纳的步骤语义对齐改进(仍按 step_index 对齐,语义对齐留给未来 change)。
- 修改 Fork 引擎对修改类型的表达能力(仍限 input/output 两类)。
- 合并采纳 / 三向合并(同 `adopt-diff-to-fork` out of scope)。

## Criteria

- 跨 trace 采纳预览返回两侧 trace 名称,UI 据此提示来源。
- 采纳确认后,新分支创建于主分支所在 trace,父分支与 trace 归属一致;归属不一致时拒绝并给出可观测原因。
- 端到端:另一条 trace 的记录值被应用到当前 trace 的新分支,执行后采纳值生效且输出覆盖不真调。
