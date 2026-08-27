# interception Specification

## Purpose
定义 Agent-Inspect 把 Agent 执行中的 LLM 调用与工具调用统一拦截、登记为决策点,并按当前执行模式决定是否真实调用的可观测行为;这是 Replay 与 Fork 的共同地基,使后续录制、回放与反事实调试得以建立。

## Requirements

### Requirement: 决策点登记
系统 SHALL 把每一次 LLM 调用与每一次工具调用登记为一个决策点,携带该次决策的完整输入与最终输出。

#### Scenario: LLM 调用登记
- **WHEN** 被拦截的 LLM 调用完成
- **THEN** 产生一个决策点,记录其输入消息、返回内容、latency 与 token 消耗

#### Scenario: 工具调用登记
- **WHEN** 被拦截的工具调用完成
- **THEN** 产生一个决策点,记录其输入参数、返回值与执行耗时

#### Scenario: 调用失败登记
- **WHEN** 被拦截的 LLM 或工具调用抛错
- **THEN** 仍产生一个决策点,其输出携带错误信息与错误标记,且不中断 Agent 原执行

### Requirement: 主流框架自动插桩
系统 SHALL 在启用后自动拦截指定框架的 LLM 调用与工具调用,无需用户改写其 Agent 代码。

#### Scenario: LangChain 自动插桩
- **WHEN** 一个 LangChain Agent 在启用拦截的进程内运行
- **THEN** 其每一步 LLM 调用与工具调用均被登记为决策点,无需在 Agent 代码中插入拦载点

#### Scenario: OpenAI 兼容 SDK 自动插桩
- **WHEN** 代码经由 OpenAI 兼容 SDK 发起 chat completion 调用且拦截启用
- **THEN** 该调用被登记为决策点,无需用户手工包装

#### Scenario: 未覆盖框架降级
- **WHEN** Agent 经由未被独立覆盖的框架封装发起决策
- **THEN** 系统不崩溃、不报错;若该调用底层落到被覆盖的调用面上则照常登记,否则不登记

### Requirement: 执行模式按上下文路由
系统 SHALL 依据当前执行模式上下文,在拦截点决定真实调用或回放记录输出。

#### Scenario: Replay 模式不真调
- **WHEN** 当前为 Replay 模式且该决策点已有记录的输出
- **THEN** 系统不发起真实 LLM 或工具调用,直接返回记录的输出

#### Scenario: Replay 缺记录输出时退回真调
- **WHEN** 当前为 Replay 模式但该决策点尚无记录的输出
- **THEN** 系统发起真实调用并记录其输出,而非以空值假装回放

#### Scenario: Fork 前缀用记录
- **WHEN** 当前为 Fork 模式且决策点序号不超过分支起点
- **THEN** 系统用记录的输出确定回放,不发起真实调用

#### Scenario: Fork 后缀真调
- **WHEN** 当前为 Fork 模式且决策点序号超过分支起点
- **THEN** 系统对该决策点发起真实 LLM 或工具调用,并记录其新输出到当前分支

### Requirement: 非侵入启停
系统 SHALL 支持以一次调用启用拦截,且关闭后对被拦截框架保持原有行为与零额外开销。

#### Scenario: 一行启用
- **WHEN** 调用启用入口
- **THEN** 该进程内其后的 Agent 执行进入拦截与登记状态

#### Scenario: 关闭零回归
- **WHEN** 拦截被禁用
- **THEN** 被拦截框架的调用按其原始路径执行,不产生额外延迟与可见副作用

### Requirement: 执行上下文传播
系统 SHALL 使同一 Agent 执行中异步产生的所有决策点归属同一 trace 与当前分支。

#### Scenario: 异步决策点同属
- **WHEN** 同一 Agent 在异步流程中产生多个决策点
- **THEN** 这些决策点共享同一 trace 标识且归属当前分支,可聚合为一条链路

#### Scenario: 分支标识隔离
- **WHEN** 存在多个分支并发执行
- **THEN** 不同分支产生的决策点各自归属其分支,互不串扰

### Requirement: 启动配置入口
系统 SHALL 经由启用入口接受可观测的配置参数,统一控制拦截生效范围与记录粒度,无需另起配置流程。

#### Scenario: 记录粒度由入口指定
- **WHEN** 启用入口显式指定记录粒度
- **THEN** 其后的决策点按指定粒度(完整或轻量)被记录

#### Scenario: 模块开关由入口指定
- **WHEN** 启用入口显式指定插桩覆盖的框架模块
- **THEN** 仅被指定的框架模块进入拦截与登记,其余保持原样不登记
