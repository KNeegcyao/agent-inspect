# Agent-Inspect 架构蓝图

> 形状文档:讲清"代码往哪放、组件边界、数据模型、执行模型、部署"。行为契约见 [openspec/](../openspec/);接口 schema 见 [contracts.md](contracts.md);开发协议见 [CLAUDE.md](../CLAUDE.md)。

## 1. 架构总览

```
你的 Agent 脚本
  │  agent_inspect.start()   ← 一行启用,自动开浏览器到本地面板
  ▼
┌───────────────────────────────────────────────────────────┐
│ Interceptor(包 llm.invoke / tool.call)                   │
│  ① 登记决策点{input_context}                              │
│  ② 按执行模式上下文路由:                                    │
│      Replay  → 返回 recorded output(不真调)                │
│      Fork    → step≤起点 用 recorded;step>起点 真调        │
│  ③ 落盘 + 经 SSE 推事件到面板                               │
└────────────┬──────────────────────────────────────────────┘
             │ 经 contextvars 携带 {trace_id,branch_id,mode,replay_cursor,branch_from_step}
   ┌─────────▼─────────────────────────────────────────────┐
   │ Local Server(进程内嵌 FastAPI)                          │
   │   store/    SQLite:traces·branches·decision_points·     │
   │             blobs·context_diffs                         │
   │   session/  活跃 trace 的分支图 + fork 调度             │
   │   api/      REST 查询 + SSE 事件流 + WS 调试指令         │
   └─────────┬─────────────────────────────────────────────┘
             └─ 托管单页 UI 资源
   ┌─────────▼─────────────────────────────────────────────┐
   │ Local Panel(单页 React + D3 + Canvas)                  │
   │   决策链路树 / 决策点检查(f全文 prompt)/ Fork 入口 /   │
   │   分支并排 / SSE 实时追加                                 │
   └────────────────────────────────────────────────────────┘
```

设计基线见 [proposal v2](../agent-inspect-proposal-v2.md) 的"架构"节与 `openspec/config.yaml#context`。

## 2. 组件边界

| 组件 | 位置 | 职责 | 不做 |
|---|---|---|---|
| **interceptor** | `agent_inspect/interceptor/` | 把 LLM/工具调用包成决策点路由点;按模式上下文决定真调/回放 | 不碰存储写盘细节(交 recorder)、不碰 UI |
| **recorder** | `agent_inspect/recorder/` | 序列化决策点、增量快照、大对象去重、落 store | 不做执行模式路由(交 interceptor) |
| **controller** | `agent_inspect/controller/` | SDK 侧与本地服务的双向通信;管理 trace/branch 与 fork 请求下发 | 不渲染(交 server/ui) |
| **_server.store** | `agent_inspect/_server/store/` | SQLite schema + 读写 + 查询 | 不含分支调度逻辑 |
| **_server.session** | `agent_inspect/_server/session/` | 活跃 trace 的分支图维护与 fork 调度 | 不做事件解码(交 api) |
| **_server.api** | `agent_inspect/_server/api/` | REST/SSE/WS 端点、消息编解码、托管 UI 资源 | 不含业务状态(交 session/store) |
| **ui**(TraceView) | `ui/` | 单页:决策树、检查、Fork 交互、并排、实时追加 | 不含任何 Agent 执行逻辑 |

跨组件数据流:Interceptor →(事件)→ api → SSE → UI;UI →(WS 指令)→ api → session → controller → 改 contextvars → Interceptor 换模式。详 [contracts.md](contracts.md)。

## 3. 数据模型

> 内部实现细节,不进 spec;为实现期对齐用。
> SQLite(MVP 唯一 backend)。blob 与 context_diffs 提供"去重 + 增量"。

```
traces          ( id PK, started_at, agent_name, root_branch_id, lifecycle )   -- lifecycle: running|done|aborted
branches        ( id PK, trace_id FK, parent_branch_id FK?, branch_from_step,
                  origin, note )                                               -- origin: record|fork
decision_points ( id PK, trace_id FK, branch_id FK, step_index, kind,          -- kind: llm|tool
                  agent_id, input_context_ref, output_ref, output_hash,
                  meta_json, cause_edge )                                      -- cause_edge: 指向引起本点的(多个)前序决策点
blobs           ( hash PK, content, size, kind )                              -- content-addressed,大对象去重
context_diffs   ( id PK, branch_id FK, step_index, diff_against_step, payload ) -- 增量上下文(d Against parent step)
```

- `input_context_ref` / `output_ref`:小体积直存,大体积指向 `blobs.hash`。
- `cause_edge`:**因果 DAG 的关键**——指向"由哪些前序决策点导致本点",表达分支/并行/重试,不止 parent-child。
- 分支回放:按 `branch_id` + `step_index` 排序取该前缀的 recorded output,逐点喂回(不发真实调用)。

## 4. 三态执行模型(一个引擎)

决策点 = `{agent_id, step_index, kind: llm|tool, input_context, output}`。Interceptor 在拦截点据**模式上下文**(经 contextvars 同步)行为如下:

| 模式 | step ≤ 分支起点 | step > 分支起点 | 真调? | 落盘? |
|---|---|---|---|---|
| **Record**(默认基线) | —(无回放) | — | 是 | 是(实时记录,供后续 Replay/Fork 消费) |
| **Replay** | 用 recorded | (无后缀) | 否 | 否(只读) |
| **Fork** | 用 recorded | — | step>起点 **是** | 是(入新 branch) |
| **Live**(Phase 2) | 在 Record 基线上加条件断点,命中则阻塞执行侧 | 同 Record | 真调 | 是 |

> **Fork 不是两个功能**:前缀 recorded(确定性、免费)+ 后缀真调(可变、产生分支)。旧的"时间-travel(只读) vs 运行时改(读写)"矛盾在此被一个模型接住。
>
> **"三态"是面向用户的三种主动姿态**:Replay / Fork / (后续)Live。`record` 是不显式调用的**默认基线**(`agent_inspect.start()` 后正常运行即实时记录,Replay/Fork 都消费它的产物);Live(Mode C)是在 `record` 之上叠加条件断点,留 Phase 2。故**实现上的 mode 字段 = `record | replay | fork`**(live 另立),与"三态"叙事不自相矛盾——`record` 是基线,三态是叠加其上的主动姿态。

contextvars 上下文(进程内,贯穿 async):
```python
{
  trace_id, branch_id, mode,            # running? fork? 
  replay_cursor, branch_from_step,      # fork 起点;replay 当前游标
}
```

## 5. 关键决策锚点(勿漂移)

- **站 OpenInference**,扩 `agent.step.cause` 因果边;不自造 OTel Agent 语义(互通优先)。
- **决策结构是 DAG/森林**,非父子树;`cause_edge` 是 DAG 的实体。
- **应急预案都写进 design.md**(类名/库/接线),**不进 spec**。
- **本地零外置后端**:SQLite 单文件、FastAPI 进程内嵌;不引 ClickHouse、不引独立 server。

## 6. MVP 目录骨架(直接照抄开发)

为 `pip install -e .` 且 `import agent_inspect` 生效,包放仓库根:

```
agent-inspect/
├── agent_inspect/                     # ← Python 包(import 名:agent_inspect)
│   ├── __init__.py                    # start()、停用入口
│   ├── interceptor/
│   │   ├── __init__.py
│   │   ├── base.py                    # 决策点抽象、模式路由点
│   │   ├── langchain_patcher.py        # LangChain 自动插桩
│   │   └── openai_patcher.py           # OpenAI 兼容 SDK 插桩
│   ├── recorder/
│   │   ├── __init__.py
│   │   ├── serializer.py              # 决策点序列化 + meta
│   │   ├── context_snap.py            # 增量上下文快照
│   │   └── dedup.py                   # blob content-addressed 去重
│   ├── controller/
│   │   ├── __init__.py
│   │   └── link.py                    # 与本地服务双向通信(SSE/WS client)
│   └── _server/                       # 进程内嵌(私有,"_"表示不独立部署)
│       ├── __init__.py                # start() 内拉起 uvicorn 的入口
│       ├── store/
│       │   ├── schema.py              # SQLite schema + 迁移
│       │   └── queries.py             # 读写 + 查询
│       ├── session/
│       │   └── branches.py            # 分支图维护 + fork 调度
│       └── api/
│           ├── rest.py                # REST 端点(查询 trace/分支)
│           ├── sse.py                 # SSE 事件流
│           └── ws.py                  # WebSocket 调试指令
├── ui/                                # 独立 npm 子项目
│   ├── package.json                   # React + Vite
│   ├── tsconfig.json
│   └── src/
│       └── TraceView/                 # 决策链路树 + 检查 + Fork 交互
├── tests/
│   ├── unit/                          # interceptor/recorder/fork 单测
│   ├── integration/                   # LangChain ReAct demo、OpenAI mock 回放
│   └── e2e/                           # 一行 start→开面→fork 一刀
├── docs/
│   ├── architecture.md                # 本文
│   ├── contracts.md
│   ├── testing.md
│   └── product.md
├── openspec/                          # spec 事实源
│   ├── config.yaml
│   ├── specs/README.md
│   └── changes/<change>/              # proposal/design/tasks + delta specs
├── pyproject.toml                     # 含 [project.optional-dependencies] dev = pytest,...
├── CONTRIBUTING.md
├── CLAUDE.md
└── README.md
```

### MVP vs 远期目录(诚实说明)

- **proposal-v2 的** `sdk/python/`、`sdk/typescript/`、`server/`、`plugin/` 是**远期多语言 monorepo 视图**,非 MVP 实际结构。
- **MVP 只 Python → 包直接放仓库根 `agent_inspect/`**,server 作为私有子模块 `agent_inspect/_server/`(进程内嵌,非独立服务,故加 `_`)。
- 远期加 TS SDK 时再拆 `sdk/{python,typescript}/`,届时 `agent_inspect/` 迁入 `sdk/python/agent_inspect/`,**影响 import path**;此项变更必须经 OpenSpec change。

## 7. 依赖矩阵(MVP)

| 侧 | 依赖 | 性质 |
|---|---|---|
| Python runtime | `httpx`(SDK ↔ server 通信)、`uvicorn`(内嵌)、`fastapi`、`aiosqlite` | runtime 必需 |
| Python dev | `pytest`(含 `pytest-asyncio`)、`langchain`、`openai`(测试用) | dev-only |
| UI | `react`、`vite`、`@types/react`、`d3` | npm |
| SDK 透传 | LangChain / OpenAI SDK(由用户项目自带,不硬绑) | **不在 runtime deps**,运行时检测 import |
| **不引入** | ClickHouse、WASM、任何 IDE SDK、独立 DB 驱动 | by-design |

## 8. 部署拓扑(单进程)

MVP **不部署独立 server**:`agent_inspect.start()` 在用户进程内拉起 uvicorn,托管 `_server` 的 ASGI app 与 UI 的静态资源(构建产物)。SSE/WS 同进程回环。退出即结束,数据留 SQLite 文件。

> 无外置后端、无独立服务进程:`local-runtime.零外置后端可用` 的实体。
