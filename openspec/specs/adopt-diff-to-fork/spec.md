# adopt-diff-to-fork Specification

## Purpose
定义把并排 diff 的差异字段一键采纳为 Fork 修改的可观测行为:从 diff 生成修改、只读预览、确认后创建新分支真实执行。与 `fork`(注入修改/后缀真调)和 `branch-diff`(字段级差异)衔接,扩展 `fork` 的修改来源为「另一分支的记录值」。

## Requirements

### Requirement: 从 diff 生成采纳修改
系统 SHALL 能把两个分支的字段级差异转换为对主分支(左侧)决策点的 Fork 修改,修改值取自对比分支(右侧)的对应字段。

#### Scenario: 采纳输入差异
- **WHEN** 对比分支的某决策点输入字段与主分支不同
- **THEN** 生成的采纳修改以该对比分支的字段值替换主分支对应输入字段,路径以 `input_context.<path>` 表示

#### Scenario: 采纳输出差异
- **WHEN** 对比分支的某决策点输出与主分支不同
- **THEN** 生成的采纳修改以对比分支的输出整段覆盖该决策点输出,路径以 `output` 表示,该决策点不再真实调用

#### Scenario: 列表索引差异
- **WHEN** 输入字段差异位于列表元素(如 `messages[0].content`)
- **THEN** 采纳修改保留列表索引路径,替换对应下标元素的值

#### Scenario: 无差异步骤不生成修改
- **WHEN** 某步骤两侧为 same(共享前缀或内容相同)
- **THEN** 该步骤不生成任何采纳修改

### Requirement: 只读采纳预览
系统 SHALL 提供只读的采纳预览,列出将应用的修改且不创建分支、不发真实调用。

#### Scenario: 预览列出修改
- **WHEN** 请求采纳预览
- **THEN** 返回将应用的修改列表(步骤/路径/值),不创建任何新分支

#### Scenario: 预览无副作用
- **WHEN** 请求采纳预览后检查已存分支
- **THEN** 分支集合与各分支决策点均未被改动,无真实 LLM 或工具调用发生

### Requirement: 采纳创建分支
系统 SHALL 在确认采纳后,按预览的修改对主分支发起 Fork,创建新分支并使后缀真实执行。

#### Scenario: 确认后创建分支
- **WHEN** 用户确认采纳
- **THEN** 以主分支为父创建新 Fork 分支,起点为指定步骤,携带采纳修改,入待执行队列

#### Scenario: 采纳后的后缀真调
- **WHEN** 采纳创建的分支执行其起点后的决策点
- **THEN** 输入被采纳修改的决策点以修改后输入发起真实调用,输出被采纳修改的决策点直接使用采纳值不真调

#### Scenario: 跨 trace 采纳
- **WHEN** 对比分支与主分支分属不同 trace
- **THEN** 采纳修改取自对比分支所在 trace 的记录值,应用到主分支所在 trace 的新分支

### Requirement: 采纳入口可见
系统 SHALL 在并排 diff 视图中提供采纳入口,并把采纳结果接入既有 Fork 创建流程。

#### Scenario: 差异步骤可采纳
- **WHEN** 用户在并排 diff 视图查看一个 diff 步骤
- **THEN** 该步骤提供「采纳到 Fork」入口,进入后展示将应用的修改清单

#### Scenario: 采纳复用 Fork 流程
- **WHEN** 用户从采纳入口确认创建
- **THEN** 创建流程与普通 Fork 一致(备注/起点/预览确认),创建后新分支出现在分支列表并可查看

### Requirement: 错误路径
系统 SHALL 在采纳请求不合法时给出可观测原因,且不产生部分状态。

#### Scenario: 空链采纳拒绝
- **WHEN** 对无任何决策点的 trace 发起采纳
- **THEN** 拒绝并给出可观测原因,不创建分支

#### Scenario: 越界起点拒绝
- **WHEN** 采纳的起点步骤超出主分支决策链范围
- **THEN** 拒绝并给出可观测原因,不创建分支

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
