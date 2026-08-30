# node-side-effect-sandbox

## Why

Node SDK 的 Fork 目前只有整链只读预览(`dry_run`):要么全真调、要么全不调。Python 侧的**副作用沙箱**(按决策点类型独立配置 `allow / dry-run / block`)是反事实实验的安全边界——"让工具假装执行/直接拦下,看 Agent 怎么反应"而不产生真实副作用。本 change 把这一能力对齐到 Node,补上双生态不对称的第二块。

检索内核、Fork 引擎、拦截器三态路由在 Node 侧都已同构,沙箱是拦截器 fork 后缀路径上的一个策略闸门 + Fork 发起时的一段校验,移植成本低。

## What Changes

- **`fork.ts`**:`requestFork` 接受 `sandbox?: Record<string, string>`(`{kind: policy}`);校验 kind ∈ {llm, tool}、policy ∈ {allow, dry-run, block},非法抛 `ForkError` 不落库;`ForkPlan` 携带 sandbox。
- **`context.ts` / `interceptor.ts`**:Cursor 增 `sandbox`;fork 后缀路径在"将要真调"的决策点上应用策略——`dry-run`:不真调、输出空、`meta.sandbox = "dry-run"`;`block`:不真调、`meta.sandbox = "blocked"`;未配置/`allow` 照常真调。优先级:注入修改 > 整链 dry_run > 沙箱 > 真调(与 Python 一致)。
- **`server.ts`**:`POST /api/forks` 透传 `sandbox`。
- **spec**:`js-sdk` 能力新增「JavaScript 运行时副作用沙箱」requirement(4 场景)。
- **测试**:单测(tool dry-run/block、llm 未配置照常真调、混合配置、非法配置拒绝不落库)+ e2e(API 携带 sandbox → 落盘 meta 标记)。

## Out of scope

- 沙箱命中的自定义替代输出(属注入修改能力);record/replay 模式应用沙箱(维持 Python 语义:只作用于 fork 后缀"将要真调"的决策点);沙箱计费/告警观测。

## Criteria

- Fork 携带 sandbox 后,后缀中命中 kind 的决策点按策略执行:dry-run/block 不真调并落盘 `meta.sandbox`,未配置的 kind 照常真调;
- 非法 kind/policy → ForkError 拒绝且不创建分支;
- API 透传 sandbox;全量测试零回归。
