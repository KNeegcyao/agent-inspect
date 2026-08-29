# recording Specification

## Purpose
定义 Agent-Inspect 把决策点持久化记录到本地、控制记录粒度与去重、保留决策点间因果关系,使历史决策可被后续回放与 Fork 读取的可观测行为。

## Requirements

### Requirement: 决策点完整记录
系统 SHALL 持久化每个决策点的完整输入、输出与可观测元数据,使其后续可被回放查询。

#### Scenario: 完整输入输出留存
- **WHEN** 一个决策点完成登记
- **THEN** 其完整输入、输出、latency 与 token 消耗被持久化,可按 trace、分支与步序查询

#### Scenario: 进程重启后可查
- **WHEN** 一个 trace 的决策点已持久化,且进程重启后再次查询
- **THEN** 其决策点输入输出仍可被读取,用于回放

#### Scenario: 异常中止前已登记者不丢
- **WHEN** Agent 执行在崩溃或中止前已完成若干决策点登记
- **THEN** 截至中止前已完成登记的决策点均已持久化,中止后仍可读取,不因未正常结束而丢失已完成者

### Requirement: 大对象去重存储
系统 SHALL 对重复的大体积输出只存储一份实体,以引用替代重复保存。

#### Scenario: 相同输出去重
- **WHEN** 多个决策点携带内容相同的大输出
- **THEN** 其实体仅存储一份,各决策点以引用关联,查询时仍返回完整内容

#### Scenario: 差异输出各自留存
- **WHEN** 多个决策点携带内容不同的大输出
- **THEN** 各自留存独立实体,互不覆盖

### Requirement: 增量上下文快照
系统 SHALL 以增量方式存储决策点输入上下文,使共享前缀只保留一份。

#### Scenario: 共享前缀不重复存
- **WHEN** 同一链路中相邻决策点的输入上下文存在大段相同前缀
- **THEN** 相同前缀只存储一次,后续决策点记录其相对前序的差异

#### Scenario: 单点回放仍获全量
- **WHEN** 对任一决策点发起回放
- **THEN** 其完整输入上下文可由增量记录重建还原

### Requirement: 可配记录粒度
系统 SHALL 提供至少两档记录粒度,使完整取证与运行开销之间可权衡。

#### Scenario: 完整记录档
- **WHEN** 配置为完整记录档运行
- **THEN** 决策点的完整 prompt 与输出生成后可被回放查看全文

#### Scenario: 轻量记录档
- **WHEN** 配置为轻量记录档运行
- **THEN** 决策点保留可观测摘要与大对象的引用标记而非全量内容,以降低开销

### Requirement: 因果关系可追溯
系统 SHALL 记录决策点之间的因果关系,使链路可按因果而非仅父子结构还原。

#### Scenario: 分支与并行可还原
- **WHEN** Agent 执行中存在分支或并行决策
- **THEN** 决策点之间的因果关系被记录,链路视图可据此重建分支与并行结构

## ADDED Requirements

### Requirement: 跨进程 trace 父子关联
系统 SHALL 允许一条 trace 声明其父 trace,使不同进程的记录可按父子关联还原为一次跨进程任务。

#### Scenario: 子 trace 携带父 id
- **WHEN** 某进程带着环境变量 `AGENT_INSPECT_PARENT_TRACE=<parent_id>` 记录一条新 trace
- **THEN** 该新 trace 的 `parent_trace_id == parent_id`,API 与面板可见该关联;不携带时父 id 为空,行为与现状一致

#### Scenario: 子 trace 可被父侧查询
- **WHEN** 查询父 trace 详情
- **THEN** 响应包含其直接子 trace 列表,子 trace 详情携带父 id

#### Scenario: 既有库向后兼容
- **WHEN** 打开一个不含父 id 列的既有数据库
- **THEN** 迁移后老 trace 的父 id 为空,已有数据不丢失
