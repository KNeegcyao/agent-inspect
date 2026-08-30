# js-sdk Specification

## ADDED Requirements

### Requirement: JavaScript 运行时副作用沙箱

系统 SHALL 允许在 JS 运行时发起 Fork 时按决策点类型配置副作用策略(allow / dry-run / block),隔离 Fork 后缀的真实副作用;未配置的类型保持真实调用,非法配置拒绝且不落库。

#### Scenario: 按 kind 配置策略

- **WHEN** 发起 Fork 时携带 sandbox 配置(`{kind: policy}`)
- **THEN** Fork 后缀中命中类型的决策点按策略执行:dry-run 与 block 不发起真实调用并标记,allow 或未配置的类型照常真实调用

#### Scenario: dry-run 模拟

- **WHEN** 某类型配置为 dry-run 后执行 Fork 后缀
- **THEN** 该类型决策点不发起真实调用,输出为空,meta 标记模拟

#### Scenario: block 阻止

- **WHEN** 某类型配置为 block 后执行 Fork 后缀
- **THEN** 该类型决策点不发起真实调用,meta 标记阻止

#### Scenario: 非法配置拒绝

- **WHEN** sandbox 中出现未知类型或未知策略
- **THEN** 拒绝创建 Fork 并给出可观测原因,不产生任何新分支
