# Agent-Inspect Live 活体调试(Mode C)— 设计

## Context

见 `proposal.md`「Why」与 `openspec/config.yaml#context`(SME):Agent 调试器缺"执行中干预"一环;Mode C(attach 运行中进程 + 条件断点 + step/continue)是 MVP 显式推迟项,现落地。约束延续:Python-only、本地内嵌服务、本地存储、站 OpenInference 语义、Interceptor 为地基、Mode A/B/C 共享同一抽象。本文件承载**内部实现**(类名/库选型/数据结构/接线步骤),不进 spec。

## Goals / Non-Goals

- 目标(Mode C):面板附加运行中的 live trace;按类型/输入内容条件断点;暂停(决策点边界)、步进、继续;暂停点检查完整输入输出、可替换输入后继续;调试作用域按 trace 隔离。
- 非目标:跨进程 attach、打断在途调用、向后步进、断点处任意代码 eval、全进程全局断点 —— 见 proposal Out of Scope。

## Design Overview

Mode C 在**既有三态统一模型**上加第四种行为:Interceptor 在每个决策点**真实执行前**,额外咨询"调试门(Debug Gate)"。调试门按 trace 持有状态,决定当前决策点是否放行、阻塞、或替换输入。

```
Agent 脚本(live trace 运行中)
  └─ Interceptor 决策点路由
       ① 登记 input_context(与 A/B 相同,执行前即登记 → 暂停时可检查完整输入)
       ② live 模式 → 咨询 Debug Gate:
            - 无断点命中且无暂停请求 → 直接放行(零额外语义)
            - 命中断点 / 有暂停请求 → 阻塞(异步 await event / 同步 event.wait)
              → 面板可见暂停点、可检查、可替换输入
              → 收到 step/continue 或 apply-modify 后放行
       ③ 真调/回放(按 A/B 既有逻辑)→ 回填 output → 落盘 + 推事件
```

模式字段扩展 `{trace_id, branch_id, mode, replay_cursor, branch_from_step}` → 增加 `live_debug: bool`。Mode C 是 Interceptor 同一段路由的又一种上下文,**不引入第二套引擎**。

## Components

### Interceptor(`sdk/interceptor/`)
- 职责:live 模式下在决策点边界咨询调试门;阻塞等待放行;支持替换待执行输入。
- 实现:在既有"登记 input_context → 按模式路由"处插入调试门咨询点。同步路径用 `threading.Event.wait()`;异步路径用 `asyncio.Event.wait()`(不阻塞事件循环,规避此前 Windows 事件循环阻塞教训)。
- 关键:阻塞发生在**决策点边界**,在途 LLM/工具调用先正常完成,不打断。
- 备选:全进程级 socket 层暂停——被否,过宽、无法按 trace 隔离。采用决策点边界门。

### Session 调试门(`agent_inspect/_server/session/`)
- 职责:per-trace 调试状态机与指令处理。
- 实现:`DebugGate` 每 trace 一个,持 `breakpoints: list[Breakpoint]`、`pause_requested: bool`、`released_steps: int|None`(None=继续至下一断点)、`pending_modify: {step, field, value}|None`。指令:
  - `attach(trace_id)` → 标记该 trace 可调试,推送已记录前缀。
  - `add_breakpoint(trace_id, kind, condition)` → 追加断点(按 kind / agent_id / 输入子串匹配的简单谓词;不做任意代码)。
  - `pause(trace_id)` → 置 `pause_requested`,下一决策点边界生效。
  - `step(trace_id)` → 置 `released_steps=1`,放行一个决策点后重新挂起。
  - `continue(trace_id)` → 置 `released_steps=None`,放行至下一断点或完成。
  - `modify(trace_id, step, field, value)` → 存入 `pending_modify`,release 后 Interceptor 用替换输入真调。
- 作用域隔离:所有状态 keyed by `trace_id`,其它 trace 的 Interceptor 不咨询该门 → 天然隔离。

### 事件与指令通道(`agent_inspect/_server/api/`)
- 职责:把调试事件推给面板,把面板指令实时送达执行侧。
- 实现:复用既有事件流通道(SSE 推送 `trace.attached / breakpoint.set / trace.paused / point.stepped / trace.resumed / point.modified`);指令经既有双向通道送达 session → 改 DebugGate。MVP 已证明 SSE+指令通道可行,不新造传输。

### UI(`web/`)
- 职责:调试工具条与断点面板。
- 实现:在既有单页上加调试工具条(Attach / Pause / Step / Continue)、断点添加器(类型 + 条件文本)、暂停态指示与暂停点高亮、暂停点输入可编辑框("应用修改并继续")。复用既有 SSE 事件驱动与决策树渲染。

## Data Model

- **决策点表不变**:登记即含 input_context(执行前),暂停时可完整检查;output 在执行后回填——暂停点天然表现为"已登记、未回填"的待执行态,无需新表。
- **新增 `breakpoints` 表**(内部,不进 spec):`(id, trace_id, kind, condition_json, enabled, created_at)`——断点跨会话保留。
- **DebugGate 内存态**:pause_requested / released_steps / pending_modify 为进程内存态,不持久化(暂停/步进是瞬态调试行为)。

## Key Decisions

- **Mode C = 第四种上下文,非第四套引擎**:与 A/B 共享 Interceptor 路由与决策点抽象;新增点仅在"真实执行前咨询调试门"。备选独立 live 引擎——被否,与"三态统一"锚点冲突。
- **决策点边界暂停,不打断在途调用**:暂停在下一决策点边界生效;可观测"等待暂停"态。备选打断在途调用——被否,不可安全取消、破坏调用语义。
- **暂停点可改输入后继续(而非重放)**:Mode C 的"改"作用于**尚未执行**的决策点输入;已执行步骤的改属 Fork 职责,二者分工明确。备选在暂停点伪造已执行步骤输出——被否,与 Fork 重叠、语义混乱。
- **作用域按 trace 隔离**:断点/暂停/步进/修改 keyed by trace_id;其它并发执行零感知。备选全局断点——被否,破坏多 Agent 并发。
- **断点条件为简单谓词,不做任意代码**:支持 kind / agent_id / 输入子串匹配。备选 eval 任意表达式——被否,越权且属 eval 引擎独立 change。
- **同步/异步两条阻塞路径**:`threading.Event` 与 `asyncio.Event` 都只阻塞 agent 执行侧,不卡 UI 服务事件循环(延续 Windows 事件循环经验)。

## Risks / Trade-offs

- [暂停阻塞与事件循环死锁] → 阻塞仅在 agent 执行侧(同步线程 `threading.Event` / 异步 `asyncio.Event.wait`),UI 服务循环保持自由;沿用既有 `asyncio.to_thread` 经验,加 e2e 死锁回归测试。
- [断点条件匹配成本] → 仅子串/相等判定,不做全文检索;超大输入条件匹配为 O(n) 子串扫描,可接受。
- [暂停态持久化缺失] → 暂停/步进为瞬态,进程退出即失效;断点落 `breakpoints` 表跨会话保留。
- [与 Replay/Fork 组合] → 已暂停的 live trace 仍可被查询历史;Fork 一个运行中 trace 的前缀按既有逻辑,后缀在其分支上执行,与 live 暂停互不干扰(后续 change 再细化 live+fork 组合场景)。

## Migration Plan

无破坏性迁移;`breakpoints` 表随 schema 增量创建;既有 traces/decision_points 结构不变,旧数据无需迁移。

## Open Questions

同 `proposal.md`「Open Questions」。
