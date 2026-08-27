# Agent-Inspect MVP — 设计

## Context

见 `proposal.md`「Why」与仓库根 `agent-inspect-proposal-v2.md`:ecosystem 已有 observability(LangFuse/Phoenix),缺 interactive agent debugger;MVP 收敛到 Replay + Counterfactual Fork + 一行起本地面板。约束见 `openspec/config.yaml#context`(SME):Python-only、本地 SQLite、内嵌 FastAPI、单页 React、站 OpenInference 语义、Interceptor 为地基、三态共享同一抽象。本文件承载**内部实现**(类名/库选型/数据结构/接线步骤),不进 spec。

## Goals / Non-Goals

- 目标(MVP):一行 `agent_inspect.start()` 即启用拦截 + 本地面板;LangChain/OpenAI 自动插桩为决策点;任一决策点可 Replay 只读回放、可 Fork(前缀回放 + 注入 + 后缀真执行);面板渲染决策链路树、可检查 prompt、可发起 fork。
- 非目标:Live 活体模式(C)、TS/Go SDK、IDE 插件、eval、ClickHouse、WASM —— 见 proposal Out of Scope。

## Design Overview

**决策点(Decision Point)** 是唯一核心抽象:`{trace_id, branch_id, step_index, agent_id, kind: llm|tool, input_context, output, meta: {latency_ms, tokens, error}}`。一次 Agent 执行是一组**带因果关系边**的决策点(DAG,非父子树)。

**Interceptor** 统一包 `llm.invoke(...)` 与 `tool.call(...)`:执行前登记决策点(`input_context`),执行后回填 `output`;并据**执行模式上下文**(由 controller 经 `contextvars` 注入的 `{trace_id, branch_id, mode, replay_cursor, branch_from_step}`)决定:
- Replay 模式 → 不真调,返回 store 中该决策点的 recorded output。
- Fork 模式 → `step_index <= branch_from_step` 用 recorded output(确定性);`> branch_from_step` 真调并记录到新 branch。
- 多 fork 经 `branch_id` + `parent_branch_id` + `branch_from_step` 重建前缀。

三种模式 = Interceptor 同一段路由逻辑的三种上下文,**避免三套代码**。

## Components

### Interceptor(`sdk/interceptor/`)
- 职责:包装 LLM 调用与工具调用为决策点路由点;按上下文模式决定真调/回放。
- 实现:LangChain 侧在 `BaseChatModel`/`Runnable` 的 generate/invoke 主入口处包装;OpenAI 侧包装 `client.chat.completions.create`;工具侧包装 LangChain `Tool`/`Runnable.invoke` 与 `@tool` 装饰器产物;登记时经 `contextvars` 取当前 `{trace_id, branch_id, mode, step_index}`。
- 备选:全进程 monkeypatch 标准库 socket——被否,过宽、不稳、难追溯。采用"在框架高语义稳定入口处包装"。
- 备选:要求用户手写包装——被否,违背"一行起"卖点。

### Recorder(`sdk/recorder/`) + Store(`server/store/`)
- 职责:序列化决策点、去重大对象、增量快照上下文、落本地存储。
- 实现:`input_context` 与父决策点做 diff,共享前缀只存一次(以 `step_index` 引用);`output` 超阈值存 hash,实体 blob content-addressed 去重存一份;`tokens/latency/error` 入 meta。
- 备选:每决策点全量快照 prompt——被否,数据量爆炸(见 v2 难点 2)。采用增量 + 去重。
- 备选:每决策点同步直写盘——被否,IO 抖动;采用批量 + WAL。

### Controller(`sdk/controller/`)+ Session(`server/session/`)
- 职责:SDK 侧与本地服务器双向通信;管理 trace/branch 与 fork 请求。
- 实现:SDK 进程内长连接(本地 WebSocket);服务器侧 session 维护活跃 trace 的分支图与 fork 调度;UI 发起的 fork 请求经 session 下发到 controller → 改 `contextvars` 切模式。

### Local Server(`server/`)
- 职责:内嵌本机服务、托管 UI 资源、查询/写入 store、调度 fork、自动开浏览器。
- 实现:单进程 FastAPI + 内嵌 `uvicorn`;启动择可用端口、`webbrowser.open` 自动开;SSE 推送决策点事件流,WebSocket 收 fork/continue 指令;无头/CI 仅打印 URL。
- 备选:独立 CLI server 要求用户先起——被否,违背零配置。采用内嵌。

### UI(`ui/TraceView/`)
- 职责:单条 trace 决策链路树渲染、决策点检查、fork 交互、分支并排、实时追加。
- 实现:React + Vite;D3 算布局、**Canvas 渲染节点**(避免几千节点 DOM 抖动);分支并排用并排子树对照;SSE 事件驱动实时追加。
- 备选:纯 DOM 渲染——被否,数千节点卡顿;采用 Canvas。

## Data Model

SQLite(MVP 唯一 backend),核心表(内部实现细节,不进 spec):
- `traces(id, started_at, agent_name, root_branch_id, lifecycle)` —— lifecycle: running|done|aborted
- `branches(id, trace_id, parent_branch_id, branch_from_step, origin: record|fork, note)`
- `decision_points(id, trace_id, branch_id, step_index, kind, agent_id, input_context_ref, output_ref, output_hash, meta_json, cause_edge)`
- `blobs(hash, content, size)` —— content-addressed 去重
- `context_diffs(id, branch_id, step_index, diff_against_step)` —— 增量上下文

因果边 `cause_edge` 指向该决策点由哪个/哪些前序决策点导致(不止 parent step),表达分支/并行/重试的 DAG。

## Key Decisions

- **站 OpenInference 语义不自造**:在 OpenInference semantic conventions 上扩 `agent.step.cause` 因果边字段;省一整轮标准化,且(import/export)与既有 observability 工具互通。备选自造 OTel Agent 语义——被否,生态孤立。
- **三态统一**:Replay/Fork/(C 推迟)共享 Interceptor 同一路由逻辑 + 上下文模式标记,非三套功能;Fork = recorded 前缀 + live 后缀,化解 v1「只读 vs 读写」矛盾。备选各自独立引擎——被否,代码重复且状态难对齐。
- **Fork 默认真执行 + 明示**:N+1 起真调 LLM/工具(才能看改后真实结果),UI 明示"将真实执行";提供 `dry_run` 把后缀也走 recorded/mock 的只读预览档。备选 fork 只读——被否,无调试价值。
- **增量快照 + 去重**:解决复杂 Agent 的上下文数据量爆炸;两档 dev(全量)/prod(摘要 + 大对象 hash)由 `agent_inspect.start(record="dev|prod")` 决定。
- **contextvars 传播**:`trace_id/branch_id/mode/replay_cursor/branch_from_step` 经 contextvars 贯穿 async;复用 LangChain 等库已验证机制,不引入全局可变单例。
- **因果 = DAG 而非树**:决策点间存显式 `cause`,表达并行/重试/多 Agent,非 parent-child 一条线。
- **已完成登记即落盘 + 并发写入串行**:崩溃/中止不丢已完成者(对应 spec `recording.异常中止前已登记者不丢`);多分支并发真执行的写入串行落盘、互不损坏(对应 `fork.并发分支写入安全`)。本地 SQLite 单写者天然串行,不为并发写锁背复杂度。trace 三态(running/done/aborted)由 `traces.lifecycle` 列承载。

## Risks / Trade-offs

- [Fork 真执行副作用] → UI 明示 + dry_run 预览;深度副作用沙箱(限制后缀对外部改写)移到 Phase 2(见 proposal Q1)。
- [上下文快照体积 vs 完整性] → dev/prod 两档;prod 大对象 hash 去重牺牲"回看全文 prompt";接受。
- [被插桩框架内部 API 漂移] → 尽量包高语义稳定入口;版本兼容矩阵 + CI 多版本测试;漂移时降级为"未拦截"并告警,不阻断用户原执行(对应 interception「未覆盖框架降级」场景泛化)。
- [无头/CI 自动开浏览器失败] → 仅打印本地 URL(见 proposal Q3 / local-runtime「无头环境降级」),降级不报错。

## Migration Plan

greenfield,无迁移、无回滚负担;若 MVP 架构后续调整,新能力一律经 change 推进。

## Open Questions

同 `proposal.md`「Open Questions」。
