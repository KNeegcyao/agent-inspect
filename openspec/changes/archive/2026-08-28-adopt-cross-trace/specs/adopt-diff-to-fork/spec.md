# adopt-diff-to-fork Specification

## ADDED Requirements

### Requirement: 跨 trace 采纳预览标注来源

系统 SHALL 在对比分支与主分支分属不同 trace 时仍能生成采纳预览,修改值取自对比分支所在 trace 的记录值,并标注两侧 trace 来源。

#### Scenario: 不同 trace 可采纳预览

- **WHEN** 对比分支与主分支分属不同 trace,且存在 diff 步骤
- **THEN** 采纳预览返回将应用的修改清单,修改值取自对比分支所在 trace 的记录值,不因 trace 不同而拒绝

#### Scenario: 预览携带来源标注

- **WHEN** 请求跨 trace 采纳预览
- **THEN** 响应包含两侧分支各自所属 trace 的名称(缺失时回退为 trace id),供界面提示修改来源

#### Scenario: 预览无副作用

- **WHEN** 请求跨 trace 采纳预览后检查存储
- **THEN** 任何 trace 的分支集合与决策点均未被改动,无真实 LLM 或工具调用发生

### Requirement: 跨 trace 采纳创建分支

系统 SHALL 在确认跨 trace 采纳后,把修改应用到主分支所在 trace 的新 Fork 分支,后缀真实执行。

#### Scenario: 确认后在主 trace 创建分支

- **WHEN** 用户确认跨 trace 采纳
- **THEN** 以主分支为父、在主分支所在 trace 创建新 Fork 分支,起点与修改与预览一致

#### Scenario: 采纳值跨 trace 生效

- **WHEN** 新分支执行其起点后的决策点
- **THEN** 输入被采纳修改的决策点使用对比 trace 的输入值发起真实调用,输出被采纳修改的决策点直接使用采纳值不真调

### Requirement: 采纳分支归属校验

系统 SHALL 在创建 Fork(含采纳确认)时保证父分支与目标 trace 归属一致,不一致时给出可观测原因且不落库。

#### Scenario: 父分支不属于目标 trace 拒绝

- **WHEN** 发起 Fork 时传入的父分支实际属于另一 trace,而目标 trace 与之不同
- **THEN** 拒绝创建并给出可观测原因,不产生任何新分支

#### Scenario: 父分支不存在拒绝

- **WHEN** 发起 Fork 时传入的父分支不存在
- **THEN** 拒绝创建并给出可观测原因,不产生任何新分支

### Requirement: 跨 trace 采纳界面可见

系统 SHALL 在采纳确认界面展示两侧 trace 归属,并在跨 trace 时明确提示修改来源。

#### Scenario: 采纳界面标注两侧 trace

- **WHEN** 打开采纳确认界面
- **THEN** 界面同时展示主分支与对比分支各自的 trace 归属

#### Scenario: 跨 trace 提示修改来源

- **WHEN** 主分支与对比分支分属不同 trace
- **THEN** 界面明确提示采纳的修改值取自对比分支所在的另一条 trace
