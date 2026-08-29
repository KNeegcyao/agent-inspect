# fork Specification

## Purpose
定义 Agent-Inspect 的反事实调试能力(旗舰):从任一已记录决策点新建分支、确定性回放前缀、注入修改、真实执行后缀,使开发者可观察"若改了这一步,后续会怎样"的可观测行为。

## Requirements

### Requirement: 从决策点发起分支
系统 SHALL 允许对任一已记录决策点发起 Fork,创建一条新分支并以该决策点为分支起点。

#### Scenario: 发起新分支
- **WHEN** 对一个已记录决策点发起 Fork
- **THEN** 创建一条归属于同一 trace 的新分支,记录其起点为该决策点

#### Scenario: 原 trace 不受影响
- **WHEN** 从某决策点 Fork 出新分支
- **THEN** 原 trace 的其余分支不被修改,各自保持独立

#### Scenario: 在根决策点 Fork
- **WHEN** 对一个 trace 的首个决策点(根决策点)发起 Fork
- **THEN** 新分支的起点为该根决策点,其前缀为空,后缀从该点真实执行

#### Scenario: 空链 Fork
- **WHEN** 对一条尚无任何决策点的空 trace 发起 Fork
- **THEN** 系统拒绝并给出可观测原因,且不创建无起点的分支;空 trace 仍可被查看(见 trace-ui 空链呈现),仅不可作为 Fork 起点

#### Scenario: 嵌套 Fork(Fork 一个 Fork 产物)
- **WHEN** 对一个由先前 Fork 产生的分支上的决策点再次发起 Fork
- **THEN** 新分支以该决策点为起点,其前缀沿用该分支的记录输出回放,与原有分支独立演化

### Requirement: 前缀确定性回放
系统 SHALL 在 Fork 的新分支上,以已记录输出回放分支起点之前的全部决策点,不发起真实调用。

#### Scenario: 前缀不真调
- **WHEN** Fork 分支回放起点之前的决策点
- **THEN** 这些决策点使用其记录输出确定回放,不发起 LLM 或工具的真实调用

#### Scenario: 前缀复现已知状态
- **WHEN** Fork 进入其分支起点
- **THEN** 此时的 Agent 决策上下文已由记录的前缀回放重建为发起 Fork 时的状态

### Requirement: 注入修改
系统 SHALL 允许在分支起点注入对决策点的修改,使后续执行据此变化。

#### Scenario: 修改 prompt
- **WHEN** 在 Fork 处将决策点的输入 prompt 替换为新内容
- **THEN** 后续执行以替换后的 prompt 作为该决策点输入

#### Scenario: 修改工具返回
- **WHEN** 在 Fork 处将某工具决策点的输出替换为指定值
- **THEN** 后续执行以该指定值作为该工具决策点的输出,不再真实调用该工具

#### Scenario: 修改参数
- **WHEN** 在 Fork 处修改工具决策点的输入参数
- **THEN** 后续执行以修改后的参数参与回放或后续真实调用

### Requirement: 后缀真实执行
系统 SHALL 在分支起点之后的决策点发起真实 LLM 或工具调用,并将新输出记录到当前分支。

#### Scenario: 后续真调
- **WHEN** Fork 分支执行起点之后的决策点
- **THEN** 这些决策点发起真实 LLM 或工具调用,而非回放旧记录

#### Scenario: 后续决策点入分支
- **WHEN** Fork 分支产生新的真实决策点
- **THEN** 这些决策点被记录到当前分支,与共享前缀的历史决策点区分

### Requirement: 真执行明示与只读预览
系统 SHALL 在发起真实执行的后缀前向用户明示其将发起真实调用,并提供只读预览档。

#### Scenario: 真执行前明示
- **WHEN** 一个 Fork 的后缀将以真实调用执行
- **THEN** 面板在执行前向用户明示该分支将真实调用 LLM 与工具

#### Scenario: 只读预览档
- **WHEN** 用户对一个 Fork 选择只读预览
- **THEN** 系统不发起任何真实 LLM 或工具调用,后续决策点不以真实输出产生,供无副作用查看

### Requirement: 分支图可枚举与并排
系统 SHALL 使同一 trace 下的多个分支可被枚举,并支持并排比较。

#### Scenario: 枚举同 trace 分支
- **WHEN** 查询一个 trace 的全部分支
- **THEN** 返回其全部分支及其起点与来源(记录或 Fork),其中原始记录分支来源标记为"记录",由 Fork 创建的分支标记为"Fork"

#### Scenario: 分支并排对照
- **WHEN** 对同一分支起点的多条分支请求并排视图
- **THEN** 各分支的决策链路以可对照方式并列呈现,差异处可被识别

### Requirement: 分支执行隔离
系统 SHALL 使不同分支的决策点互不串扰,各自独立演化。

#### Scenario: 分支独立演化
- **WHEN** 多个 Fork 分支同时推进其各自后缀
- **THEN** 每个分支的决策点与真实调用结果各自归属,不互相覆盖或污染

#### Scenario: 并发分支写入安全
- **WHEN** 多条分支的后缀同时真实执行并产生决策点
- **THEN** 各分支的写入互不损坏,任一分支的决策点均可被完整读回,不以并发为由丢失或篡改

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
