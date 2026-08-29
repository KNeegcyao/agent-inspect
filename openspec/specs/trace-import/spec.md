# trace-import Specification

## Purpose
把外部观测工具导出的 span 树文件导入为本系统的可调试 trace:外部 LLM/工具调用 span 映射为决策点,携带完整输入与输出,与自录 trace 同构。导入后的链路可被查看、并可发起反事实 Fork(前缀用导入输出回放、后缀真实执行),从而打通「别人录好的链路 → 本工具调试」的通路。导入是只读映射,不改写、不清洗外部数据。

## Requirements

### Requirement: 从外部 span 导出创建可调试 trace

系统 SHALL 支持把一份遵循既定开源观测语义约定的 span 导出 JSON 导入为一条完整 trace,其中 LLM 调用 span 与工具调用 span 分别映射为对应 kind 的决策点,映射保持顺序、输入输出与因果关系。

#### Scenario: LLM 与工具 span 映射为决策点

- **WHEN** 导入一份同时含 LLM 调用 span 与工具调用 span 的合法导出 JSON
- **THEN** 生成一条 trace,两类 span 分别成为 `kind=llm` 与 `kind=tool` 的决策点;决策点顺序与 span 树的遍历顺序一致;导入的 trace 生命周期为已完成(历史运行)

#### Scenario: 输入输出保真(前缀回放可用)

- **WHEN** 一个外部 span 携带完整的调用输入(如消息列表、工具参数)与输出(如回复内容、工具返回值)
- **THEN** 对应决策点的 `input_context` 与 `output` 分别承载该输入与输出,经既有决策点查询读回的内容与导出一致

#### Scenario: 因果关系保留

- **WHEN** 导出的 span 树中某 span 是另一 span 的父级(或列表中前序)
- **THEN** 子决策点的因果边(`agent.step.cause`)指向其前序决策点,链在面板上按序呈现

#### Scenario: 无法识别的 span 忽略并计数

- **WHEN** 导出中存在无法识别为 LLM 或工具调用的 span
- **THEN** 该 span 不生成决策点,导入结果回报被忽略的 span 数量;其余 span 正常导入

### Requirement: 导入链路参与既有调试流

系统 SHALL 使导入生成的 trace 与自录 trace 在查看与调试行为上无差别:面板可辨识其导入来源,且可对其发起反事实 Fork。

#### Scenario: 面板可辨识导入来源

- **WHEN** 导入成功后面板呈现 trace 列表与链路视图
- **THEN** 该 trace 带「导入」来源标记,其决策点查看、分支图与分支 diff 与自录 trace 行为一致

#### Scenario: 对导入链路发起 Fork

- **WHEN** 对导入 trace 的某决策点发起 Fork,随后用户运行自己的 Agent
- **THEN** 该次执行消费此 Fork:起点之前用导入的输出确定性回放(不发起真实调用),起点之后真实执行并记录到新分支

### Requirement: 非法导入可观测拒绝

系统 SHALL 对不合法的导入请求给出可观测原因并拒绝,不产生任何数据写入。

#### Scenario: 缺失 span 树拒绝

- **WHEN** 提交的导入内容不是 JSON,或不含可解析的 span 树
- **THEN** 返回 4xx 与可观测的错误原因,不创建任何 trace

#### Scenario: 空 span 树拒绝

- **WHEN** 导出 JSON 可解析,但不包含任何可映射为决策点的 span
- **THEN** 返回 4xx 与可观测原因,不创建任何 trace
