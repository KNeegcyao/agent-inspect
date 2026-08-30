# node-live-debug Design

## 概述

把 Python `debug.py` 的状态机移植到 Node(`sdks/node/src/debug.ts`),阻塞原语从 `threading.Event` 换成 **Promise resolver**:暂停 = 保存 resolver 并 await;指令 = resolve。`AsyncLocalStorage` 游标挂 `liveDebug` 标记,路由在决策点边界(真实调用前)咨询调试门。REST 端点与 Python 同契约,面板调试工具栏零改动点亮。

## 1. 调试门(`debug.ts`)

```ts
class DebugGate {
  attached = false
  breakpoints: Breakpoint[]           // {id, trace_id, kind?, agent_id?, condition?}
  pauseRequested = false
  stepMode = false
  pendingModify: {step, field, value} | null
  pausedAt: number | null
  pausedPayload: dict | null
  private waiter: ((v?: unknown) => void) | null
  private releaseAction: "continue" | "step" | null
}
```

- `consult(dp)`:未附加或未命中 → 直接返回 null(零开销);命中 → 置 paused 状态、登记 payload、`await new Promise(r => this.waiter = r)`;被唤醒后取 `releaseAction`(step → stepMode=true;continue → false)、取出 pendingModify 返回;
- 指令:`attach()` / `pause()` / `step(atStep?)` / `resume(atStep?)` / `modify(step, field, value, action)` / `state()` / `addBreakpoint` / `removeBreakpoint`;
- **at_step 绑定**(与 Python 修复后语义一致):`_issueRelease(atStep, action)` —— atStep 给定且 `pausedAt !== atStep` → 忽略(返回 false);命令仅在匹配当前暂停点时 resolve waiter;
- `modify`:暂存 pendingModify,仅当 `pausedAt === step` 才释放(重复投递不误放);
- 命中判定 `_shouldPause`:手动暂停 → 单步 → 断点(kind/agent_id 相等、condition 为输入 JSON 子串),断点须 enabled;
- `DebugController`:traceId → gate 注册表,`ensureGate` 时载入 store 既有断点(跨会话)。

## 2. 拦截器(`interceptor.ts` / `context.ts`)

- `Cursor` 增 `liveDebug = false`;
- `route()` 在构建 dp 后、`decide()` 前:`if (cursor.liveDebug) { const mod = await debug.consult(dp); if (mod) { applyInputMod(dp, mod); if (makeModifiedCall) 用替换 call } }`(async 路径天然不阻塞事件循环);
- Session 装配:`new Interceptor(store, fork, onEvent, debug)`;`acquireContext` 时 `cursor.liveDebug = !!debug` 并 `debug.ensureGate(traceId)`。

## 3. 断点持久化(`store.ts`)

JSON store 增 `breakpoints: [{id, trace_id, kind?, agent_id?, condition?, enabled, created_at}]`;`addBreakpoint / listBreakpoints(traceId) / removeBreakpoint`;gate 创建时载入。

## 4. 服务端点(`server.ts`,与 Python 同契约)

- `POST /api/debug/{tid}/attach`(trace 须 running,否则 404/422)→ gate.state()
- `GET /api/debug/{tid}/state`
- `GET|POST /api/debug/{tid}/breakpoints`、`DELETE .../breakpoints/{bp_id}`
- `POST /api/debug/{tid}/pause` / `step`(body 可选 at_step,响应 `{ok, action, released}`)/ `continue`(同)/ `modify`({step, field, value} → gate.modify,释放绑定 step)

## 5. 测试

- 单测(`tests/debug.test.ts`):断点命中(kind/子串)/ 条件不命中零阻塞 / 手动暂停 / 单步恰一步 / at_step 过期忽略 / 重复 modify 不误放 / 断点持久化;
- 集成(`tests/live.test.ts`):慢速 mock Agent(每步间 50ms)后台线程执行,主线程经 HTTP:attach → 设断点 → 等待 paused_at=0 → step → 等 paused_at=1 → modify → continue → 完成后断言落盘输入已替换;断点跨 Session 保留;
- 面板契约:端点路径/响应形状与 Python 逐字段一致(工具栏零改动可用)。

## 6. 已知差异(相对 Python,记录于 SDK README)

- Python 断点阻塞发生在 Agent 线程(`Event.wait`),JS 为 await promise——语义等价;
- Python 咨询点在 async 路径经 `to_thread`,JS 天然 async。
