# trace-ui Specification

## ADDED Requirements

### Requirement: 运行统计摘要

系统 SHALL 在面板 trace 头部展示当前查看链路的运行统计摘要:耗时合计与 token 用量合计,只聚合链路上携带统计数据的决策点;无统计数据的项不展示。

#### Scenario: 耗时合计

- **WHEN** 当前查看的链路中有决策点携带耗时
- **THEN** 面板头部显示该链路的耗时合计(单位自适应,毫秒/秒)

#### Scenario: token 合计

- **WHEN** 链路中决策点携带 token 用量(输出中的 usage,或 meta 中的输入/输出 token 数)
- **THEN** 面板头部显示该链路的 token 用量合计

#### Scenario: 无统计不展示

- **WHEN** 当前链路没有任何耗时或 token 统计数据
- **THEN** 对应合计不显示,不展示零值占位
