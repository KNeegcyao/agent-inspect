# Agent-Inspect 接口契约

> 把 schema / HTTP / WS / 入口签名固化到"可直接照抄实现"的粒度,供前后端对接与换机器开发。
> 这是实现期契约,**行为事实源仍是 [openspec/](../openspec/)**;本文是实现约定,改契约需走 spec(若影响可观测行为)或此处增订。

## 1. 决策点对象 schema(Agent 执行的原子)

每次 LLM 调用或工具调用产生一个决策点。字段固化:

```jsonc
// DecisionPoint
{
  "id": "dp_01H8....",                 // 唯一 id(ULID/uuid)
  "trace_id": "tr_01H8....",
  "branch_id": "br_01H8....",
  "step_index": 3,                     // 该 branch 内单调用序列号(0-based)
  "kind": "llm",                       // "llm" | "tool"
  "agent_id": "researcher",            // 产生该点的 agent 标识(多 agent 时区分)

  "input_context": { ... },            // 见 §2,大体积经 ref 指向 blob

  "output": { ... },                   // 见 §2,大体积经 ref 指向 blob
  "output_hash": "sha256:...",         // output 的 content-hash,供去重/并排对照

  "cause_edge": ["dp_01H8...parentA"], // 因果:导致本点的前序决策点 id 数组(DAG,可多个)

  "meta": {
    "latency_ms": 742,
    "tokens_in": 980,
    "tokens_out": 213,
    "error": null,                     // 非 null 时携带 {code, message}
    "model": "gpt-4o",                 // llm kind 时填;tool 时 null
    "tool": null,                      // tool kind 时填工具名;llm 时 null
    "ts": "2026-08-25T03:21:00Z"       // 由 SDK 注入(脚本不应自取时钟)
  }
}
```

- `cause_edge` 链向**因**它产生的点(非父 step 这一条线),表达分支/并行/重试的 DAG。
- 并排对照靠 `output_hash`:同起点两条分支后缀,hash 不同即"分叉发生了"。

## 2. input_context / output 形态

按 `kind`:

```jsonc
// kind == "llm"
"input_context": {
  "messages": [ { "role": "system", "content": "..." }, ... ],
  "model": "gpt-4o",
  "params": { "temperature": 0.7, "tools": [...] }   // 实际调用参数,Fork 注入修改的就是这里
},
"output": { "content": "...", "tool_calls": [...] }

// kind == "tool"
"input_context": {
  "tool": "web_search",
  "args": { "query": "..." }                          // Fork 注入修改 args 即此处
},
"output": { "result": "...", "is_error": false }
```

**大对象**:当一个字段序列化后大于阈值(默认 4KB,可配),实体进 `blobs` 表,本字段替换为 `{"blob_ref": "sha256:..."}`。查询时透明解引用还原。

## 3. 分支对象 schema

```jsonc
{
  "id": "br_01H8....",
  "trace_id": "tr_01H8....",
  "parent_branch_id": "br_root....",   // 原始记录分支为 null
  "branch_from_step": 5,               // 分支起点 step;<= 分支起点的点用 recorded 回放
  "origin": "fork",                    // "record"(原始)| "fork"(Fork 产生)
  "note": "lower temperature"          // Fork 时的可读说明(可选)
}
```

## 4. 执行模式上下文(contextvars 承载,进程内贯穿 async)

```python
# 伪代码,字段契约
```
| 字段 | 类型 | 取值 |
|---|---|---|
| `trace_id` | str | 当前 trace |
| `branch_id` | str | 当前 branch |
| `mode` | str | `"record"`(默认:正常运行时实时记录,基线态)/ `"replay"` / `"fork"` |
| `replay_cursor` | int | replay 当前步序(默认无) |
| `branch_from_step` | int | fork 起点;`mode=="fork"` 时有效 |
| `dry_run` | bool | fork 起点之后是否仍走 mock(recorded)而非真调 |

> **拦截器唯一读取这套上下文决定行为**(见 [architecture §4](architecture.md#4-三态执行模型一个引擎));SDK/Server 经 controller 写入它来切模式。

## 5. SDK 启用入口签名

```python
agent_inspect.start(
    *,
    record: str = "dev",        # "dev"(全量快照)| "prod"(摘要 + 大对象 hash),见 recording.可配记录粒度
    modules: list[str] | None = None,   # ["langchain", "openai"];None = 全部已支持框架
    port: int = 0,              # 0 = 自动择可用端口;非 0 尝试指定
    headless: bool | None = None,        # None = 自动检测;"无头/CI 降级"见 local-runtime
    autostart_browser: bool = True,      # False 则只开服务,不主动唤起浏览器
) -> Session
```

- `record` 与 `modules` 对应 spec `interception.启动配置入口`。
- 返回 `Session`,提供 `session.stop()`(零回归关闭)与 `session.url`(面板地址,供无头环境打印与人工打开)。
- 关闭后该进程内拦截卸载,被插桩框架回到原始路径(`interception.关闭零回归`)。

## 6. Interceptor 契约(实现期对齐)

拦截点(按支持面):
- LangChain:`BaseChatModel`/`Runnable` 的 generate/invoke 主入口(`langchain_patcher.py` 包装,**不全进程 monkeypatch socket**,见 design.md 决策)。
- OpenAI 兼容 SDK:`client.chat.completions.create`(`openai_patcher.py`)。
- 工具:LangChain `Tool`/`@tool` 产物的 invoke。

每个拦截点的统一行为序列:
```
enter:
  dp = 登记决策点(填 kind/agent_id/input_context)
  依 mode_ctx 决定:
    replay  → 从 store 取该 (branch_id, step_index) 的 recorded output 返回;若无记录(spec Replay 缺记录输出时退回真调)→ 落 lives
    fork    → step_index <= branch_from_step ? recorded : 真调
    record  → 真调
  (fork 的 dry_run=True 时,step>branch_from_step 也不真调)
leave(或真调返回后):
  填 output / output_hash / meta(latency,tokens,error)
  recorder.dedup + 增量快照 + 落盘(已完成登记即落盘)
  经 SSE 推 一条 decision_point 事件到面板
error:
  仍登记 dp,meta.error 填写;不中断 Agent 原执行(interception.调用失败登记)
```

> 未覆盖框架:拦截点不存在,自然不登记(`interception.未覆盖框架降级`——其底层落到被覆盖的 `chat.completions.create` 则照常登记,否则不登记)。

## 7. 本地服务 HTTP / SSE / WS 协议

基址:`http://127.0.0.1:<port>`(自动择端口,见 §5)。同进程回环。

### REST(查询为主)
```
GET  /api/traces?lifecycle=done|aborted|running   →  trace 列表(按生命周期筛选,见 local-runtime.Trace 生命周期)
GET  /api/traces/{trace_id}/branches             →  该 trace 全部分支(含 origin: record|fork)
GET  /api/traces/{trace_id}/branches/{branch_id}?from_step=0&to_step=N
                                                 →  该分支决策点区间(分页/窗口,供链路树渲染)
GET  /blob/{hash}                                →  大对象实体解引用
```

### SSE(事件流,面板订阅)
```
GET  /api/traces/{trace_id}/stream    (Content-Type: text/event-stream)
event: decision_point
data: { ...DecisionPoint... }            // 执行中实时追加(trace-ui.实时呈现新决策点)
event: branch_added
data: { ...Branch... }                    // Fork 创建新分支时推送
event: trace_done | trace_aborted         // 生命周期终态(trace-ui.完成态呈现)
```

### WebSocket(调试指令,面板 → server → controller → 改 contextvars)
路径:`ws://127.0.0.1:<port>/api/traces/{trace_id}/control`,JSON 帧:

```jsonc
// 发起 Fork + 注入修改
{ "type": "fork",
  "branch_from_step": 5,
  "origin_branch": "br_root",         // 从哪条分支 fork
  "modifications": [                  // 注入:对分支起点那个决策点
    { "target_step": 5, "field": "input_context.params.temperature", "value": 0.2 },
    { "target_step": 5, "field": "output", "value": { "result": "..." } }   // 改工具返回
  ],
  "dry_run": false,                   // true = 只读预览,后缀不发真调
  "note": "lower temperature" }

// 继续执行某分支后缀(若执行侧处于可步进回调——Phase 2 Live 为主,MVP 可选)
{ "type": "continue", "branch_id": "br_01H8...." }
```

server 回帧(ACK/状态):
```jsonc
{ "type": "fork_accepted", "branch_id": "br_new...." }
{ "type": "fork_rejected", "reason": "empty_trace_no_root" }   // 见 fork.空链 Fork
```

> 字段名是契约约定;若 REST/WS 协议演进影响可观测行为,需走 OpenSpec change。

## 8. 与 OpenInference 语义映射

站在 OpenInference semantic conventions 上扩,不自造:
- `llm.*` / `tool.*` 标准 span 属性 → 映射到 DecisionPoint 的对应 kind + meta。
- **扩展因果边**:`agent.step.cause` = `decision_points.cause_edge`(OpenInference 无此字段,我们加)。
- 导入/导出(Phase 3):能吃别人产出的 OpenInference trace 做 Fork。MVP 不实现导出,但 schema 已对齐以免返工。
