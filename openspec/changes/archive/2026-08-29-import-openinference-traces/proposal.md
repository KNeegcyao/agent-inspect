# import-openinference-traces

## Why

Agent-Inspect 的旗舰能力是**反事实 Fork**:拿一段已记录的执行,改一个决策,真的重跑后缀。但目前 Fork 的原料只能是**本工具自己录的 trace**——调试者必须先用自己的 Agent 跑一遍,才有得 Fork。而开发者手里最不缺的恰恰是**别人录好的链路**:生产环境的观测平台、同事分享的一次运行、问题现场留下的导出文件。

Roadmap(Phase 3)明确了这一步:「OpenInference 导入导出——**吃别人的 trace 做 fork**」。站 OpenInference 语义是本项目既定立场(config#context),把外部 span 树映射为决策点,是打通「观测世界 → 调试世界」的关键一跳:

- 拿到生产上出问题的那次运行(已经录好),导入面板,直接在出事的决策点发起 Fork——前缀确定性回放(零真调),后缀用**自己修好的 Agent** 真执行,立刻看到「如果当时改了会怎样」。
- 导入的 trace 与自录 trace 同构(同样的决策点模型、同样的存储),Fork / 分支 diff / 采纳差异**零改动全量复用**——这验证了决策点抽象的普适性。

## What Changes

- **后端(新增 `agent_inspect/importer.py`)**:解析遵循 OpenInference 语义约定的 span 导出 JSON(LLM/TOOL span kind、input/output 属性、span 父子树),映射为 Agent-Inspect 决策点:
  - `LLM` span → `kind=llm` 决策点;`TOOL` span → `kind=tool` 决策点;其余 span 不生成决策点(导入结果回报忽略计数)。
  - span 树的深度优先顺序 → `step_index`;父 span → `agent.step.cause` 因果边。
  - 属性中的完整输入(messages/参数)与输出 → `input_context` / `output`(Fork 前缀回放的原料);span 时长 → `meta`。
  - 导入 trace 的 `lifecycle=done`(历史运行)、`agent_name` 取导出中的会话/服务标识、带可观测的导入来源标记。
- **API**:`POST /api/traces/import`(请求体为 span 导出 JSON)→ 落库并返回 trace id / 决策点数 / 忽略数;非法导出 4xx + 可观测原因,不落库。
- **UI**:trace 列表工具栏加「导入」入口(选本地 JSON 文件);导入成功的 trace 带「导入」徽标,点开即可查看链路与发起 Fork(与自录 trace 无差别)。
- **spec**:新增 `trace-import` 能力(导入映射 / 与既有调试流打通 / 非法导入拒绝)。
- **测试**:导入映射单元测试(LLM/工具/未知 span、顺序与因果边、输入输出保真)、fork 导入 trace 的集成测试、导入 API e2e;离线示例脚本 `examples/react_agent_import_trace.py`(无需 API key:合成 span 导出 → 导入 → 在导入链路上 Fork)。

## Out of scope

- **导出**自身 trace 为该格式(与导入对称,留作后续 change;本 change 先打通"吃进来"这半条路)。
- OTLP/gRPC 实时接收、watch 目录、远程观测平台直连拉取——本 change 只做**文件级导入**。
- 非 JSON 格式(ProtoBuf / CSV)与超大文件优化。
- 对导入链路做"结构改写"(增删 span、重排)——导入是只读映射,不清洗。

## Criteria

- 提交合法 span 导出 JSON 后,生成一条 `lifecycle=done` 的 trace:LLM/TOOL span 分别成为 `llm`/`tool` 决策点,顺序与 span 树一致,每个决策点携带完整输入与输出,父 span 关系表现为因果边。
- 导入 trace 在面板带「导入」徽标;决策点查看、Fork、分支 diff 与自录 trace 行为一致。
- 对导入 trace 发起 Fork 后,下一个 Agent 执行消费该 Fork:前缀用导入的 recorded output 回放(不真调),后缀真调。
- 非法导出(缺 span 树 / 非 JSON)返回 4xx 与可观测原因,不落库;无法识别 kind 的 span 被忽略且导入结果回报忽略计数。
- 全量测试通过;既有能力不回归。
