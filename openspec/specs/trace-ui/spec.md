# trace-ui Specification

## Purpose
定义 Agent-Inspect 本地面板在单页内呈现一条 trace 的决策链路、检查决策点细节、发起反事实 Fork 与区分分支,以及实时追加执行中决策点的可观测行为。

## Requirements

### Requirement: 单条 trace 决策链路视图
系统 SHALL 在单页内以链路树呈现一条 trace 中决策点的推理与调用结构。

#### Scenario: 链路树渲染
- **WHEN** 打开一条 trace 的面板
- **THEN** 其决策点按 思考→工具→结果 的链路结构以树形呈现,可逐节点展开层级

#### Scenario: 多分支结构呈现
- **WHEN** 该 trace 含多条分支
- **THEN** 各分支在树结构中可被识别与展开,共享前缀处可见分叉

### Requirement: 决策点细节检查
系统 SHALL 允许查看任一决策点的完整输入与输出。

#### Scenario: 查看完整 prompt
- **WHEN** 选中一个 LLM 决策点
- **THEN** 其完整输入消息与返回内容以可读全文呈现

#### Scenario: 查看工具输入输出
- **WHEN** 选中一个工具决策点
- **THEN** 其输入参数与返回值以可读形式完整呈现

### Requirement: Fork 交互入口
系统 SHALL 提供在面板内对任一决策点发起 Fork 与注入修改的入口。

#### Scenario: 面板发起 Fork
- **WHEN** 在面板对某一决策点触发 Fork 并提交修改
- **THEN** 系统据此创建新分支并按修改执行,且在面板呈现该新分支

#### Scenario: 修改在提交后生效
- **WHEN** 用户在 Fork 入口提交对 prompt 或工具返回的修改
- **THEN** 该修改作为分支起点的注入,反映于后续决策点

### Requirement: 分支并排区分
系统 SHALL 在视图中原分支与 Fork 分支以可区分的方式呈现。

#### Scenario: 分支来源标注
- **WHEN** 面板呈现多条分支
- **THEN** 原始分支与由 Fork 产生的分支以可辨识的视觉差异区分

#### Scenario: 分支差异可对照
- **WHEN** 用户选择对照原分支与某一 Fork 分支
- **THEN** 两者的决策链路以并排方式呈现,便于识别分歧起点与差异

### Requirement: 执行中实时追加
系统 SHALL 在 Agent 执行过程中实时将新决策点追加进面板,无需手动刷新。

#### Scenario: 实时呈现新决策点
- **WHEN** Agent 执行中持续产生新决策点
- **THEN** 面板无需手动刷新即实时追加呈现这些决策点

#### Scenario: Fork 后续实时回流
- **WHEN** Fork 分支的后缀真实执行并产生新决策点
- **THEN** 这些新决策点实时回流并追加至该分支视图

### Requirement: Trace 终态呈现
系统 SHALL 在一条 trace 或其分支执行结束时,使面板呈现其终态,与进行中状态可区分。

#### Scenario: 完成态呈现
- **WHEN** 一条 trace 或其分支执行结束
- **THEN** 面板标识该 trace 或分支为已完成,不再期待新决策点追加

#### Scenario: 空链呈现
- **WHEN** 打开一条尚无任何决策点的 trace
- **THEN** 面板呈现其空态并提示尚未产生决策点,而非空白或报错

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

### Requirement: 面板主题切换

系统 SHALL 支持在深色与浅色两套面板主题间切换:切换即时生效(含链路画布重绘),偏好持久化,默认深色。

#### Scenario: 切换即时生效

- **WHEN** 点击主题切换入口
- **THEN** 面板配色立即在深色/浅色间切换,决策链画布同步重绘,全部功能行为不受影响

#### Scenario: 偏好持久化

- **WHEN** 切换主题后重新打开面板
- **THEN** 面板保持上次选择的主题

#### Scenario: 默认深色

- **WHEN** 从未切换过主题时打开面板
- **THEN** 面板呈现深色主题
