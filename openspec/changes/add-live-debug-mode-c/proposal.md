# Agent-Inspect Live 活体调试(Mode C)— 提案

## Why

MVP 已交付 Replay + Counterfactual Fork + 一行起本地面板:开发者能在**事后**对已记录执行回放、重建分支。但"调试器"体验还缺最后一环:**执行中干预**——Agent 正跑着,我能不能像 pdb / DevTools 一样暂停它、在断点停下、步进、甚至改一下这步的输入再继续?这是 observability 永远给不了的,也是 Mode A/B 覆盖不到的:它们都要求先有完整记录,而 Mode C 允许在运行中即时打断与修改。`openspec/config.yaml#context` 将 Mode C 定为 MVP 显式推迟项,本 change 使其落地。

## What Changes

- 新增 **live-debug** 能力:面板可附加运行中的 live trace;按类型/输入内容设置条件断点;随时暂停(决策点边界)、按决策点步进、继续;暂停点可检查完整输入输出、可替换输入后继续;全部调试作用域仅限被调试的 trace 与分支。
- 三态统一原则延续:Mode C 不是第四套引擎,是 Interceptor 同一路由逻辑下的又一种上下文行为(Mode A/B/C 共享决策点抽象与拦截器)。

## Capabilities

- **New Capabilities**
  - `live-debug` — 运行中附加、条件断点、暂停/步进/继续、暂停点检查与运行时修改、作用域隔离。
- **Modified Capabilities**
  - (none — 行为均以新能力 delta 表达,不改既有能力契约)

## Impact

- 代码:interceptor 增加 live 模式上下文与暂停协调;session 增加调试门(attach/breakpoint/pause/step/continue/modify);事件与指令通道扩展调试事件;UI 增加调试工具条与断点面板。
- 测试:live 模式单测(断点命中/条件/步进/暂停边界/作用域隔离)、e2e(运行中 attach → 设断 → 暂停 → 步进 → 改输入 → 继续 → 看到差异)、零回归(既有 record/replay/fork 用例)。
- 依赖:不新增外部依赖(基于既有内嵌服务与事件通道)。
- 兼容:关闭拦截零回归;live 调试仅在用户启用时生效,不改变 Agent 正常行为(见 spec「附加不改变执行」)。

## Out of Scope (Non-Goals of this change)

- 跨进程附加(attach 到非本进程的另一 Agent 执行)——归入"多 Agent 跨进程追踪"后续 change。
- 中断进行中的调用(暂停仅在决策点边界发生,不打断在途 LLM/工具调用)。
- 向后步进/回退(反向步进归 Replay 的只读回放;live 步进仅向前)。
- 断点处执行任意脚本/表达式(内置 eval 引擎另立独立 change)。
- 全进程级全局断点(调试始终按 trace 作用域隔离,不提供影响所有 Agent 的全局断点)。

## Open Questions

- Q1(建议):暂停语义定为"决策点边界暂停"——不打断在途调用。**默认采用**:暂停在下一个决策点边界生效,给出可观测的"等待暂停"状态;若后续需要中断在途调用,另立 change。
- Q2(建议):运行时修改语义定为"替换待执行输入后继续",而非"重放已执行步骤"(重放是 Fork 的职责)。**默认采用**。
