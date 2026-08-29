# llm-decision-sandbox

## Why

上一轮「Fork 副作用沙箱」只把策略选择暴露给了**工具**决策点:面板上单选「工具调用副作用策略」,`createFork` 只发 `sandbox: {tool: policy}`。但**后端沙箱闸门本来就是按 `dp.kind` 泛化的**——`SANDBOX_KINDS` 含 `llm`,`_sandbox_policy` 对 LLM 决策点同样生效。缺的只是 UI 暴露与场景覆盖:

现状:
- ForkPanel 无法对 **LLM 决策点** 选策略(默认放行),想"模拟/阻止 LLM 调用"只能靠注入修改 `output` 或整链 `dry_run`。
- 沙箱标记展示不区分 kind——LLM 被拦与工具被拦的文案一样,看不出拦的是哪一类。

真实调试场景里,"挡掉 LLM 真调"非常有用:想验证**不给模型发 prompt**、或**用空输出模拟**时 Agent 的后续行为(等价于免费/离线的"如果模型这次没响应"实验),而不必改 prompt 或写死注入值。LLM 真调有成本与不确定性,把它纳入与工具同构的策略闸门,能让"反事实实验"的边界控制更完整。

## What Changes

- **后端**:零改动。`_sandbox_policy` 已按 `dp.kind` 泛化,`llm` 属合法 kind;`SANDBOX_KINDS`/`SANDBOX_POLICIES` 已覆盖。只需补齐针对 LLM 的测试以锁定语义。
- **UI(ForkPanel)**:新增「LLM 决策点策略」单选组(`allow` / `dry-run` / `block`,默认 `allow`),与既有「工具调用副作用策略」并列;提交时对非默认的 kind 携带 `sandbox: {llm: p, tool: q}`(省略 `allow`)。
- **UI(沙箱标记)**:决策点详情按 `kind` 区分文案——LLM 决策点被拦显示「LLM 模拟(沙箱)」/「LLM 被沙箱阻止」,工具决策点维持现文案。
- **spec**:`fork.副作用沙箱` 增加 LLM 场景(LLM dry-run / LLM block / 混合配置),与工具场景对称。
- **测试**:
  - 单元:LLM `dry-run`(不真调 + `meta.sandbox=dry-run`,工具未配置照常真调);LLM `block`(不真调 + `meta.sandbox=blocked`);混合配置 `{llm: block, tool: allow}`(工具照常、LLM 拦下)。
  - e2e:API 携带 `sandbox: {llm: dry-run}` 发起 Fork → 落库 LLM 决策点 `meta.sandbox=dry-run`、工具照常真调。

## Out of scope

- 沙箱命中时的**自定义替代输出**(如注入预设文本)——那已属于注入修改(`output` field),不在本 change。
- 对 record 模式 / replay 模式应用沙箱——沙箱只作用于 fork 后缀"将要真调"的决策点,维持现状语义。
- 沙箱触发计费/告警等观测增强。

## Criteria

- ForkPanel 可分别选择 LLM 决策点策略与工具调用副作用策略(默认均为放行)。
- 提交非默认策略后,`POST /api/forks` 携带 `sandbox: {llm: ...}` 或 `{tool: ...}` 或两者;`allow` 不落 payload。
- LLM 决策点被 `dry-run`/`block` 命中时不发起真实调用,落盘 `meta.sandbox` 为 `dry-run`/`blocked`;未配置的 kind 照常真调。
- 决策点详情沙箱标记按 kind 区分文案(LLM / 工具)。
- 全量测试通过;既有沙箱单测与 e2e 不回归。
