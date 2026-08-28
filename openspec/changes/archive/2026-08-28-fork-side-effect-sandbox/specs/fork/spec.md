# fork Specification

## ADDED Requirements

### Requirement: Fork 副作用沙箱

系统 SHALL 允许在发起 Fork 时按决策点类型(kind)配置副作用策略,对"将真实调用"的决策点隔离真实副作用,默认行为保持真实调用不变。

#### Scenario: 按 kind 配置策略

- **WHEN** 发起 Fork 时携带 `sandbox` 配置(`{kind: policy}`),其中 `policy ∈ {allow, dry-run, block}`
- **THEN** 该 Fork 后缀中 kind 命中的决策点按策略执行:`allow` 真实调用、`dry-run` 不真调并标记模拟、`block` 不真调并标记阻止;未配置的 kind 保持真实调用

#### Scenario: 工具 dry-run 模拟

- **WHEN** 对工具类决策点配置 `dry-run` 后执行 Fork 后缀
- **THEN** 该工具决策点不发起真实调用,其 `meta` 记录 `sandbox: "dry-run"`,输出为空(与只读预览档同构)

#### Scenario: 工具 block 阻止

- **WHEN** 对工具类决策点配置 `block` 后执行 Fork 后缀
- **THEN** 该工具决策点不发起真实调用,其 `meta` 记录 `sandbox: "blocked"`

#### Scenario: 未配置保持真调

- **WHEN** 发起 Fork 时未配置 sandbox,或某 kind 显式配置为 `allow`
- **THEN** 该 kind 的决策点照常发起真实调用,行为与无沙箱时一致

#### Scenario: 非法配置拒绝

- **WHEN** `sandbox` 中出现不存在的 kind 或非法的 policy
- **THEN** 拒绝创建该 Fork 并给出可观测原因,不产生任何新分支

### Requirement: 沙箱标记可观测

系统 SHALL 把被沙箱拦截或模拟的决策点以标记形式呈现,供界面与查询区分。

#### Scenario: 决策点携带沙箱标记

- **WHEN** 一个决策点被沙箱以 `dry-run` 或 `block` 处理
- **THEN** 该决策点的 `meta` 携带 `sandbox` 字段,界面据其展示「模拟执行(沙箱)」或「被沙箱阻止」

#### Scenario: 全局只读预览优先

- **WHEN** Fork 处于整链只读预览(`dry_run`)
- **THEN** 所有后缀决策点均不真调,沙箱策略不再单独生效
