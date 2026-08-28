# fork-side-effect-sandbox

## Why

Fork 后缀"真调"目前会真实调用 LLM 与工具——工具调用可能带来真实副作用(写文件、发请求、改数据库)。现状只有两个极端:整链真调(`dry_run=False`,默认)或整链只读预览(`dry_run=True`),中间没有任何档位:

- 想"LLM 照常跑、但工具别真执行"做不到;只能要么全真调、要么全部只看预览。
- README 已把 **Fork side-effect sandbox** 列为 Phase 2(目前只有 `dry_run` 预览),本 change 落地该缺口。

本 change 为 Fork 引入**按决策点类型(kind)的副作用策略**,把「真实副作用」从「真实执行」中解耦出来:默认行为不变(向后兼容),但用户可以给工具类调用配置"模拟执行(dry-run)"或"阻止执行(block)",在不牺牲前缀回放与 LLM 执行的前提下隔离危险副作用。

## What Changes

- **后端(沙箱策略模型)**:Fork 携带可选 `sandbox` 配置——`{kind: policy}`,`kind ∈ {llm, tool}`,`policy ∈ {allow, dry-run, block}`;未配置的 kind 保持真实调用(默认 `allow`,现有行为不变);非法 kind / policy 以可观测原因拒绝(422,不创建分支)。`ForkPlan` 与 `ExecutionCursor` 透传该配置。
- **后端(拦截器接入)**:fork 后缀在"将真调"的决策点上按 `dp.kind` 查沙箱策略——`dry-run` / `block` 不发起真实调用,并在该决策点 `meta` 记录 `sandbox` 标记(`dry-run` / `blocked`);`allow` 或未配置则照常真调。全局 `dry_run`(整链只读)优先级高于沙箱,二者正交。
- **API**:`POST /api/forks` 接受可选 `sandbox` 字段(透传给 `request_fork`)。
- **UI**:
  - ForkPanel 提供「工具调用副作用策略」选择(放行 / 模拟执行 / 阻止),默认放行;
  - 决策点详情展示 `meta.sandbox` 标记,区分「模拟执行(沙箱)」与「被沙箱阻止」。
- **测试**:
  - 单元:`dry-run` 工具不真调且 meta 标记、`block` 工具不真调且 meta 标记、`allow`/未配置照常真调、非法 kind / policy 拒绝且不落库。
  - e2e:创建带沙箱的 fork → 执行 → 工具步骤无真调、meta 有沙箱标记、LLM 步骤照常真调。

## Out of scope

- 进程级 / 系统级沙箱(命名空间、seccomp、网络隔离)——本 change 只做**决策点粒度**的执行策略。
- 沙箱策略的持久化与跨会话记忆——策略随 Fork 请求即时生效,不落库。
- 对非 Fork(record / replay)执行的副作用策略——沙箱只作用于 Fork 后缀真调。
- 精细到单个 step / agent_id 的策略——仅按 kind 配置,满足当前用例。

## Criteria

- 带 `sandbox: {"tool": "dry-run"}` 的 fork:工具决策点不真调,`meta.sandbox == "dry-run"`,LLM 决策点照常真调。
- 带 `sandbox: {"tool": "block"}` 的 fork:工具决策点不真调,`meta.sandbox == "blocked"`。
- 未配置 sandbox 的 fork:行为与现状完全一致(全真调)。
- 非法 sandbox 配置(kind 或 policy 不合法):拒绝创建并给出可观测原因,不落库。
