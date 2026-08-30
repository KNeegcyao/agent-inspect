# recording Specification

## ADDED Requirements

### Requirement: trace 删除管理

系统 SHALL 支持删除单条 trace:级联移除其全部分支与决策点,不影响同库其它 trace;面板提供删除入口并经确认后执行。

#### Scenario: 删除级联且隔离

- **WHEN** 删除一条含根分支、Fork 分支与决策点的 trace
- **THEN** 该 trace 及其全部分支与决策点被移除:列表不再出现,详情与决策点查询不可得;同库其它 trace 的分支与决策点保持完好

#### Scenario: 删除不存在的 trace

- **WHEN** 对不存在的 trace 标识发起删除
- **THEN** 返回 404 与可观测原因

#### Scenario: 面板删除入口

- **WHEN** 用户在面板中对某条 trace 触发删除并确认
- **THEN** 该 trace 从列表移除;若其为此前选中的 trace,面板回到未选择状态
