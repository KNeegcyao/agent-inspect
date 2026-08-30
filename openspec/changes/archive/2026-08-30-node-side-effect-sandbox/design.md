# node-side-effect-sandbox Design

## 概述

移植 Python `fork.py` 的沙箱语义:`{kind: policy}` 配置 + 拦截器 fork 后缀的策略闸门。决策点构建与落盘路径零改动——沙箱只在"将要真调"之前拦截并打 meta 标记。

## 1. 校验与承载(`fork.ts` / `context.ts`)

- 常量:`SANDBOX_KINDS = ["llm", "tool"]`、`SANDBOX_POLICIES = ["allow", "dry-run", "block"]`;
- `requestFork(opts)` 增 `sandbox?: Record<string, string>`:遍历条目,kind/policy 非法 → `ForkError`(`invalid sandbox kind/policy`),不创建分支;合法 → `ForkPlan.sandbox = sandbox`;
- `Cursor` 增 `sandbox?: Record<string, string>`;`acquireContext` 消费 fork plan 时带入。

## 2. 策略闸门(`interceptor.ts`)

`decide()` fork 后缀路径,优先级(与 Python 一致):output 注入 → input 修改 → 整链 dryRun → **沙箱** → 真调:

```ts
const policy = this.sandboxPolicy(cursor, dp); // "dry-run" | "blocked" | null
if (policy) {
  dp.meta["sandbox"] = policy;
  return { native: opts.reconstruct(null), needsRecord: true };
}
```

`sandboxPolicy`:无配置/类型未配置/allow → null;dry-run → "dry-run";block → "blocked"。

## 3. API(`server.ts`)

`POST /api/forks` 透传 `body["sandbox"]`;非法配置由 `ForkError` 走既有 422 通道。

## 4. 测试

- 单测(`tests/sandbox.test.ts`):
  - tool dry-run:不真调 + `meta.sandbox="dry-run"` + 输出空;llm 未配置照常真调;
  - tool block:`meta.sandbox="blocked"`;
  - 混合 `{llm: block, tool: allow}`:llm 拦下、tool 真调;
  - 非法 kind / policy → ForkError,分支集合不变。
- e2e:`POST /api/forks` 携带 `sandbox: {tool: "dry-run"}` → 执行后 fork 分支点 meta 标记、无真实工具调用;非法 sandbox → 422 且无新分支。
