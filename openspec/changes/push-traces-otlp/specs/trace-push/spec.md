# trace-push Specification

## Purpose

把本系统的一条 trace 的决策链推送到用户指定的标准 span 推送协议收集端点(HTTP + JSON 形态),载荷复用导出能力的 span 映射。推送是只读操作:不改变本地任何数据;送达结果与失败原因对用户可观测。

## ADDED Requirements

### Requirement: 推送链路到收集端点

系统 SHALL 支持把一条 trace 的决策链推送到用户提供的收集端点:载荷由既有导出映射生成(每个决策点对应一个 span、属性承载完整输入输出),以标准推送协议的 HTTP+JSON 形态提交。

#### Scenario: 推送载荷与导出映射一致

- **WHEN** 对一条含 LLM 与工具决策点的 trace 向某收集端点发起推送
- **THEN** 端点收到的载荷中,每个决策点对应一个 span,其类型、名称、顺序、父子关系与属性内容与导出同一 trace 所得文件一致

#### Scenario: 送达成功回报统计

- **WHEN** 收集端点以 2xx 响应
- **THEN** 推送结果回报送达的 span 数与端点响应状态,本地数据不发生任何变化

### Requirement: 推送失败可观测

系统 SHALL 对推送失败给出可观测原因,且失败不产生本地写入。

#### Scenario: 端点不可达

- **WHEN** 收集端点无法连接
- **THEN** 给出可观测的错误原因,不发生本地写入

#### Scenario: 端点返回非 2xx

- **WHEN** 收集端点以非 2xx 状态响应
- **THEN** 给出包含端点状态码的可观测错误,不发生本地写入

#### Scenario: trace 不存在拒绝

- **WHEN** 对不存在的 trace 标识发起推送
- **THEN** 返回 404 与可观测原因

### Requirement: 面板推送入口

系统 SHALL 在面板提供对任一 trace 的推送入口,允许填写收集端点地址并发起推送。

#### Scenario: 面板发起推送并看到结果

- **WHEN** 在面板中对一条 trace 填入端点地址并触发推送
- **THEN** 推送结果(送达统计或错误原因)在面板可见
