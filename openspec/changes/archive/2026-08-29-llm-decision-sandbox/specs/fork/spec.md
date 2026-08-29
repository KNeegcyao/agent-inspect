# fork Specification

## ADDED Requirements

### Requirement: LLM 决策点沙箱

系统 SHALL 允许对 LLM 类决策点配置与工具同构的副作用策略(`allow` / `dry-run` / `block`),使 LLM 真调可被模拟或阻止,且与工具策略互相独立生效。

#### Scenario: LLM dry-run 模拟

- **WHEN** 对 LLM 类决策点配置 `dry-run` 后执行 Fork 后缀
- **THEN** 该 LLM 决策点不发起真实调用,其 `meta` 记录 `sandbox: "dry-run"`,输出为空(与只读预览档同构)

#### Scenario: LLM block 阻止

- **WHEN** 对 LLM 类决策点配置 `block` 后执行 Fork 后缀
- **THEN** 该 LLM 决策点不发起真实调用,其 `meta` 记录 `sandbox: "blocked"`

#### Scenario: 混合配置按 kind 独立生效

- **WHEN** 发起 Fork 时对 LLM 与工具分别配置不同策略(如 `{llm: block, tool: allow}`),或只配置其中一类
- **THEN** 各 kind 的决策点各自按自身策略执行:命中的被拦、未配置或 `allow` 的照常真调,互不影响

#### Scenario: LLM 未配置保持真调

- **WHEN** 发起 Fork 时未对 LLM 配置 sandbox,或显式配置为 `allow`
- **THEN** LLM 决策点照常发起真实调用,行为与无沙箱时一致
