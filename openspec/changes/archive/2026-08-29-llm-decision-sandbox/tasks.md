# llm-decision-sandbox Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:LLM 决策点沙箱的 why / 方案 / 范围
- [x] 1.2 `specs/fork/spec.md` delta:新增「LLM 决策点沙箱」requirement(4 场景)

## 2. UI

- [x] 2.1 ForkPanel 增加「LLM 决策点策略」单选组(allow/dry-run/block,默认 allow),与工具策略并列
- [x] 2.2 提交组装 `sandbox` 仅含非默认 kind;`allow` 不落 payload;提交后两态复位
- [x] 2.3 决策点沙箱标记按 kind 区分文案(LLM 模拟/阻止 vs 工具模拟/阻止)

## 3. 测试

- [x] 3.1 单元:LLM `dry-run`(不真调 + meta.sandbox=dry-run;工具未配置照常真调)
- [x] 3.2 单元:LLM `block`(不真调 + meta.sandbox=blocked)
- [x] 3.3 单元:混合配置 `{llm: block, tool: allow}`(LLM 拦下、工具真调)
- [x] 3.4 e2e:API 携带 `sandbox: {llm: dry-run}` → LLM 决策点 meta 标记、工具照常真调
- [x] 3.5 全量 pytest 通过(既有工具沙箱不回归)

## 4. 验证

- [x] 4.1 `openspec validate 2026-08-29-llm-decision-sandbox` 通过
- [x] 4.2 `cd web && npm run build` 通过

## 5. 发布

- [x] 5.1 README 沙箱说明覆盖 LLM 决策点
- [x] 5.2 `openspec archive 2026-08-29-llm-decision-sandbox --yes`
- [x] 5.3 commit + push(`94a3fdf`)
