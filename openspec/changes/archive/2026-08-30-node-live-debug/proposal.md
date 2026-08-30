# node-live-debug

## Why

双生态不对称里最大的一块:**Node SDK 没有 Live 调试**。Python 侧可以附加运行中的 Agent、设断点、单步、改输入、继续——JS Agent 用户只能事后看。而 Node 侧的基础设施其实都已就位:AsyncLocalStorage 游标(可挂 liveDebug 标记)、决策点路由(可插咨询点)、内嵌服务(可加端点),且**面板的调试工具栏本就按同一 REST 契约实现**——Node 侧补齐端点与调试门,工具栏直接点亮,零面板改动。

语义与 Python 侧逐项对齐(包括后来加固的 **释放指令绑定暂停点 at_step**——重复投递不误放后续暂停点;这是 Python 侧踩过坑后的成熟语义,Node 从第一天就带上)。

## What Changes

- **`sdks/node/src/debug.ts`(新增)**:`DebugGate`(单 trace 状态机:attached / 断点(kind/agent_id/输入子串)/ 手动暂停 / 单步 / 待替换输入 / paused_at)+ `DebugController`(traceId → gate 注册表)。阻塞用 Promise resolver(`consult` 在暂停时 await,指令线程 resolve),不阻塞事件循环(与 Python `asyncio.to_thread` 策略对应)。
- **`context.ts` / `interceptor.ts`**:Cursor 增 `liveDebug`;路由在决策点边界(真实调用前)咨询调试门;命中 → 暂停等待指令 → 放行时应用待替换输入(经既有 `makeModifiedCall` 通道真实执行)。
- **`store.ts`**:断点落库(跨会话保留),gate 创建时载入既有断点。
- **服务端点**(与 Python 同契约):`POST attach`、`GET state`、`GET/POST/DELETE breakpoints`、`POST pause/step/continue`(step/continue 支持可选 `at_step` 绑定,响应带 `released`)、`POST modify`;attach 限定 running trace。
- **spec**:`js-sdk` 能力新增「JavaScript 运行时 Live 调试」requirement(附加与断点 / 暂停步进 / 改输入继续 / 重复投递幂等,共 4-5 场景)。
- **测试**:gate 状态机单测(命中/条件不命中/单步/at_step 幂等/改输入)、HTTP 集成 e2e(慢速 mock Agent 全流程:attach → 断点命中 → step → modify → continue → 落盘见差异)。

## Out of scope

- 异步 `aroute` 之外的运行时形态(Python 同构已覆盖 async);任意代码条件断点(与 Python 一致,只支持 kind/agent_id/子串);断点面板之外的批量操作。

## Criteria

- JS Agent 运行中:面板调试工具栏可附加;kind 断点命中后该决策点暂停(状态可查、输入可看);step 恰执行一个决策点再暂停;modify 替换输入后继续 → 落盘输入为修改后值;continue 至完成;
- 重复/过期的 step/continue(携带旧 at_step)被忽略,不跳过暂停点;
- 断点跨会话保留;attach 限定 running trace(否则 404/422 可观测);
- 全量 node:test 通过、Python pytest 零回归;面板调试工具栏在 Node 面板可用。
