# interception Specification

## ADDED Requirements

### Requirement: 流式调用插桩

系统 SHALL 支持对流式 LLM 调用(stream 模式)的插桩:chunk 原样透传给调用方,同时在流耗尽时以累积的完整输出登记决策点;回放命中的流式决策点以合成流返回记录的完整内容。流开始前的调试/回放/注入/沙箱语义与非流式一致。

#### Scenario: 流式调用的透传与登记

- **WHEN** Agent 以流模式发起 LLM 调用并迭代消费全部 chunk
- **THEN** 调用方收到的 chunk 内容序列与不插桩时一致;流耗尽后,该决策点以累积的完整输出(内容与工具调用)登记,输入完整可查

#### Scenario: 回放命中返回合成流

- **WHEN** 回放/分支前缀命中一个流式记录的决策点
- **THEN** 调用方迭代合成流可读取记录的完整内容(经 delta 路径),且不发起真实调用

#### Scenario: 流开始前的模式语义一致

- **WHEN** 流式调用处于 Fork 后缀(注入修改 / dry_run / 沙箱命中)或 Live 暂停边界
- **THEN** 语义与非流式一致:注入后以修改输入真实调用;dry_run 与沙箱命中不发起真实调用并打标记;Live 命中在流开始前暂停
