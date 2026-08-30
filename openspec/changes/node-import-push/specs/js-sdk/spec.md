# js-sdk Specification

## ADDED Requirements

### Requirement: 导入与推送

系统 SHALL 在 JS 运行时提供外部 span 导出 JSON 的导入(与既有导入语义一致:两形态、按类型映射、非法拒绝不落库)与链路推送到用户收集端点的能力;两者均可经面板使用。

#### Scenario: 导入为可调试链路

- **WHEN** 经面板或 API 提交合法的 span 导出 JSON
- **THEN** 生成与自录同构的 trace(LLM/工具决策点、顺序、因果边、完整输入输出),非法导出返回 422 与可观测原因且不落库

#### Scenario: 推送链路到收集端点

- **WHEN** 对一条 trace 指定收集端点发起推送
- **THEN** 链路以与导出一致的映射送达端点(载荷经包装协议传输);成功回报送达统计,失败给出可观测原因且不改动本地数据
