# Agent-Inspect Live 活体调试(Mode C)— 任务清单

> 顺序:Interceptor live 模式 → 会话调试门 → 事件与指令通道 → UI 调试工具条 → 测试/验收 → 文档。每项勾选即完成。
> 对应 change:`add-live-debug-mode-c`;能力 delta spec 见 `specs/live-debug/spec.md`。

## 1. Interceptor Live 模式

- [ ] 1.1 执行上下文扩展 live 调试标记,与 Mode A/B 共享同一段路由逻辑
- [ ] 1.2 决策点边界咨询调试门:命中断点 / 有暂停请求 → 阻塞等待 step/continue
- [ ] 1.3 暂停点输入可替换:release 后以替换输入真实执行,否则原输入
- [ ] 1.4 同步(`threading.Event`)与异步(`asyncio.Event`)两条阻塞路径均不卡 UI 服务事件循环

## 2. 会话调试门(session)

- [ ] 2.1 per-trace `DebugGate`:attach / breakpoint / pause / step / continue / modify 指令
- [ ] 2.2 条件断点:按 kind / agent_id / 输入内容子串匹配的简单谓词(不做任意代码)
- [ ] 2.3 断点与调试状态按 trace 隔离,不影响其它 trace / 分支
- [ ] 2.4 暂停点状态机:登记(待执行)→ step/continue → 执行/回填;`breakpoints` 表持久化

## 3. 事件与指令通道

- [ ] 3.1 事件流:attach / breakpoint.set / paused / stepped / resumed / modified 事件推送面板
- [ ] 3.2 指令通道:面板 → 服务 attach/breakpoint/pause/step/continue/modify 实时送达执行侧

## 4. UI 调试工具条

- [ ] 4.1 Attach 入口 + 运行中 trace 附加
- [ ] 4.2 断点面板:按类型/条件添加、启用、删除
- [ ] 4.3 Pause / Step / Continue 工具条 + 暂停态指示
- [ ] 4.4 暂停点高亮 + 完整输入输出检查 + 输入可编辑(应用修改并继续)

## 5. 测试与验收

- [ ] 5.1 live 模式单测(断点命中/条件不命中/暂停边界/步进/继续/作用域隔离)
- [ ] 5.2 e2e:运行中 attach → 设断 → 暂停 → 步进 → 改输入 → 继续 → 看到差异
- [ ] 5.3 未启用 live 时既有 record/replay/fork 用例零回归
- [ ] 5.4 能力 delta spec 全部 Scenario 逐条自检通过
- [ ] 5.5 `openspec validate --all` 通过

## 6. 文档与发布

- [ ] 6.1 README:Mode C quickstart(运行中暂停/断点/步进)
- [ ] 6.2 design.md 关键决策链入 docs(Why)
- [ ] 6.3 apply+验证通过后 `openspec archive add-live-debug-mode-c --yes`,delta 并入主规格
