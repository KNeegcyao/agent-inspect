# node-live-debug Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:Node Live 调试的 why / Promise 阻塞原语 / at_step 语义
- [x] 1.2 `specs/js-sdk/spec.md` delta:「JS 运行时 Live 调试」1 requirement 共 4 场景

## 2. 核心实现

- [x] 2.1 `debug.ts`:DebugGate 状态机(Promise waiter、at_step 绑定、pendingModify)+ DebugController;单测(命中/条件/单步/at_step 幂等/重复 modify)
- [x] 2.2 store 断点持久化(增删查 + 跨会话载入);Cursor.liveDebug + interceptor 咨询点;单测

## 3. 服务与集成

- [x] 3.1 服务端点(attach/state/breakpoints/pause/step/continue/modify,同契约含 at_step/released);集成测试(HTTP 全流程:慢速 Agent attach→断点→step→modify→continue→落盘差异)
- [ ] 3.2 面板调试工具栏连通(Node 面板下可用)

## 4. 验证与发布

- [x] 4.1 全量 node:test 通过;Python pytest 零回归;`npm run build` 通过
- [ ] 4.2 SDK README 语义差异说明更新;`openspec validate --all` 通过
- [ ] 4.3 `openspec archive node-live-debug`;commit + push
