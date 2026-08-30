# trace-stats-summary

## Why

Agent 调试时两个最常被问到、却要人工逐点相加才能回答的数字:**这条链路花了多久**、**花了多少 token**。数据其实一直在——LangChain 插桩把 `tokens_in/out` 写进决策点 `meta`,OpenAI 插桩把 `usage` 留在输出里,每个决策点也都有 `latency_ms`——但面板从不聚合,用户只能自己加。

本 change 在面板 trace 头部加**运行统计摘要**:对当前查看的链路聚合耗时合计与 token 合计,以 chip 形式展示。纯前端聚合(零后端改动、零 schema 改动),双 SDK 自动受益;无统计数据的链路不显示对应 chip(不制造"0 tokens"的误导)。

范围克制:只聚合**当前选中的主分支链路**(用户正在看的那条);不做跨分支/跨 trace 汇总、不做成本换算(价格因模型而异,属于 eval/账单工具的领地,与项目立场一致地不做)。

## What Changes

- **UI(`web/src/chain.js` + `App.jsx`)**:
  - `chain.js` 新增纯函数 `summarizeChain(points)`:`{latencyMs, tokens}`——耗时合计 = Σ `meta.latency_ms`(有点才计);token 合计 = Σ(优先 `output.usage.total_tokens`,回退 `meta.tokens_in + meta.tokens_out`,数值才计);
  - trace 头部(rel-bar)新增统计 chips:`Σ 耗时 …` 与 `Σ … tokens`,无数据不渲染。
- **spec**:`trace-ui` 能力新增「运行统计摘要」requirement(3 场景)。
- **验证**:Node 示例链(输出含 usage)浏览器实测 chips 数值;纯离线链(Python 脚本模型无 usage)仅显示耗时 chip。

## Out of scope

- 成本换算(价格表);跨分支/跨 trace 汇总;后端聚合端点(客户端聚合已覆盖当前查看链路);流式调用的逐 chunk 统计。

## Criteria

- 链路中决策点带耗时 → 头部显示耗时合计(毫秒/秒自适应单位);
- 决策点带 token 用量(`usage.total_tokens` 或 `meta.tokens_in/out`)→ 头部显示 token 合计;
- 无统计数据 → 对应 chip 不渲染;切换分支时摘要随链路更新。
