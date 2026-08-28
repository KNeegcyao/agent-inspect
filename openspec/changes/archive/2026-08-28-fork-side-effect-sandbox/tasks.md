# fork-side-effect-sandbox Tasks

## 1. 后端:沙箱策略模型与校验

- [ ] 1.1 `fork.py` 增加 `SANDBOX_KINDS` / `SANDBOX_POLICIES` 常量;`request_fork` 接受 `sandbox` 参数并校验非法 kind / policy(可观测原因,不落库)
- [ ] 1.2 `ForkPlan` 增加 `sandbox` 字段并随计划透传

## 2. 后端:执行侧透传与闸门

- [ ] 2.1 `_context.py` `ExecutionCursor` 增加 `sandbox` 槽与参数
- [ ] 2.2 `interceptor/base.py` `acquire_context` 透传 `sandbox=plan.sandbox`;`_decide` / `_adecide` fork 分支加沙箱闸门(dry-run/block → 不真调 + `meta.sandbox`)

## 3. 后端:API

- [ ] 3.1 `/api/forks` 接受可选 `sandbox` 字段透传给 `request_fork`

## 4. UI

- [ ] 4.1 ForkPanel 增加「工具调用副作用策略」选择(allow / dry-run / block),默认 allow,createFork 携带 `sandbox`
- [ ] 4.2 决策点详情展示 `meta.sandbox` 标记(模拟执行 / 被沙箱阻止)
- [ ] 4.3 styles.css 增加策略选择与沙箱标记样式

## 5. 测试

- [ ] 5.1 单元:工具 dry-run → 不真调 + `meta.sandbox == "dry-run"`,LLM 照常真调
- [ ] 5.2 单元:工具 block → 不真调 + `meta.sandbox == "blocked"`
- [ ] 5.3 单元:未配置 sandbox → 行为与现状一致(全真调);allow 显式配置 → 真调
- [ ] 5.4 单元:非法 kind / policy → ForkError 拒绝 + 不落库
- [ ] 5.5 e2e:带 sandbox 的 fork 全链路(工具无真调、meta 标记、LLM 真调)
- [ ] 5.6 全量 pytest 通过 + `openspec validate` 通过 + vite build 通过

## 6. 文档与发布

- [ ] 6.1 README 补「Fork 副作用沙箱」说明,更新 Phase 2 规划
- [ ] 6.2 `openspec archive fork-side-effect-sandbox --yes`
- [ ] 6.3 commit + push
