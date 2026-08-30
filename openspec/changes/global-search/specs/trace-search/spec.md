# trace-search Specification

## ADDED Requirements

### Requirement: 跨 trace 全局搜索

系统 SHALL 支持一次查询跨全部 trace 检索决策点(匹配语义与单 trace 搜索一致),结果按 trace 分组返回,每组标注 trace 标识与命中合计,trace 按最近优先排列。

#### Scenario: 按 trace 分组返回命中

- **WHEN** 提交全局查询且多个 trace 中存在命中
- **THEN** 结果按 trace 分组:每组标注 trace 标识、名称与命中合计;无命中的 trace 不出现;每组内命中附上下文片段,且每组最多返回前若干条(合计数完整)

#### Scenario: 全部无命中返回空

- **WHEN** 提交全局查询且所有 trace 均无命中
- **THEN** 返回空结果集

#### Scenario: 缺查询拒绝

- **WHEN** 全局搜索未提供查询子串
- **THEN** 返回 422 与可观测原因

### Requirement: 面板全局搜索入口

系统 SHALL 在面板侧栏提供全局搜索框:输入查询后列表区切换为按 trace 分组的命中视图,支持直达定位与恢复。

#### Scenario: 分组结果与直达定位

- **WHEN** 在侧栏输入全局查询
- **THEN** 列表区展示按 trace 分组的命中(trace 头可进入该 trace;命中片段可点击,点击后面板定位到该 trace 的对应决策点——必要时切换分支并选中)

#### Scenario: 清空恢复列表

- **WHEN** 清空全局查询
- **THEN** 侧栏恢复常规 trace 列表
