# import-openinference-traces Design

## 概述

新增一条**只读导入通路**:把遵循 OpenInference 语义约定的 span 导出 JSON(OTLP JSON 信封或扁平 span 列表两种形态)映射为 Agent-Inspect 的 trace + 决策点。核心原则:**导入产物与自录 trace 同构**——同样的表、同样的查询、同样的 Fork 消费流,因此 fork/diff/采纳零改动复用;导入器本身不碰拦截器与记录路径。

## 1. 接受的输入形态(`agent_inspect/importer.py`)

导入函数 `import_trace(store, recorder, payload: dict) -> ImportResult` 接受两种 JSON 形态:

1. **OTLP JSON 信封**:`{"resourceSpans": [{"scopeSpans": [{"spans": [...]}]}]}`(Phoenix 等遵循 OpenInference 的导出形状)。属性为 OTel 数组形态 `[{key, value: {stringValue|intValue|doubleValue|boolValue}}]`,导入器先拍平成 `{key: python_value}`;OpenInference 结构化属性(`llm.input_messages` / `llm.output_messages` / `llm.invocation_parameters` / `tool.parameters` / `tool.return_value`)的值是 **JSON 字符串**,需二次 `json.loads`(失败则按纯文本处理,不拒绝导入)。
2. **扁平 span 列表**:`{"spans": [{...}]}`,属性已是 `{key: value}` 对象(示例与测试用此形态合成)。

span 识别:读 `openinference.span.kind` 属性;`LLM` → llm、`TOOL` → tool;**其它 kind(AGENT/CHAIN/RETRIEVER/缺失)不生成决策点**,计入 `skipped`。span 时间属性:`startTimeUnixNano`(OTLP)或 `start_time`(扁平,毫秒或秒,启发式:>1e12 视为 ms)。

## 2. 映射规则(与既有插桩器形态对齐——Fork 回放的前提)

| 外部 span | 决策点 | input_context | output |
|---|---|---|---|
| `openinference.span.kind=LLM` | `kind="llm"`,`agent_id=span.name` | `{"messages": <llm.input_messages 拍平为 [{role, content}]>, "model": <llm.model_name>, "params": <llm.invocation_parameters>}`(缺省项省略) | `{"content": <首条 assistant 消息 content>, "tool_calls": <output_messages 中的 tool_calls 或 []>}`——**与 `_shape_llm` / `_shape_response` 同形**,保证 LangChain/OpenAI 插桩器的 `reconstruct` 可直接回放 |
| `openinference.span.kind=TOOL` | `kind="tool"`,`agent_id=<tool.name 或 span.name>` | `{"tool": <tool.name>, "args": <tool.parameters>}` | `{"result": <tool.return_value>}`——与 `Serializer.tool_output` / `_reconstruct_tool` 同形 |

- **顺序与因果**:span 列表按 `(start_time, span_id)` 稳定排序后**深度优先遍历**(parent_id 建树);遍历序即 `step_index`(0-based);每个决策点的 `cause_edge=[前一个决策点 id]`(与 record 模式的线性因果链一致,嵌套 span 的父子关系已体现在遍历序中)。
- **meta**:span 时长(ms)→ `meta.latency_ms`;`meta.imported = true` + 原始 `span_id` 便于溯源。
- **trace 头**:`agent_name` 取 resource 的 `service.name`(缺省 `"imported"`);`lifecycle=done`;`started_at` 取最早 span 起始时间(秒)。落库走**既有** `store.create_trace_with_root` + `store.write_decision_point`(复用增量快照/去重序列化,不新开写路径)。
- **空映射拒绝**:可映射 span 数为 0 → `ImportError("no importable spans")`,不落库(spec「空 span 树拒绝」)。

## 3. API(`_server/app.py`)

`POST /api/traces/import`,请求体即导入 JSON(两种形态均可;`Content-Type: application/json`):

```python
res = import_trace(session.store, session.recorder, body)   # ImportError → 422 {"error": str}
return {"trace_id": ..., "decision_points": n, "skipped": k, "root_branch_id": ...}
```

- 非 JSON / 缺 span 集合 → 422 + 可观测原因(与既有 422 风格一致)。
- 事件总线发布 `trace.imported`(SSE 已订阅者自动刷新列表,无需前端轮询特殊处理)。

## 4. UI(`web/`)

- **api.js**:`importTraces(payload)` → `POST /api/traces/import`。
- **App.jsx**:trace 列表工具栏加「导入」按钮 → `<input type="file" accept=".json">` → 读文本 `JSON.parse` → 调 API → 成功后刷新 trace 列表并选中新 trace;失败 `setError`(复用现有错误条)。
- **「导入」徽标**:trace 列表项与详情头,当 trace 的决策点 `meta.imported` 存在(或 API 返回的 `imported: true`)时展示;样式复用既有「跨进程」徽标风格。为避免逐点扫描,`GET /api/traces/{id}` 响应加 `imported: bool`(后端查首决策点 meta 或 trace 级标记),列表接口同理。
- **trace 级来源标记的实现**:traces 表**不加列**——`agent_name` 前缀法不可取(污染语义);改为导入器在 root 分支的决策点 meta 写 `imported`,API 层聚合:trace 详情/列表的 `imported` 字段 = `COUNT(决策点 meta LIKE '%"imported": true%')>0`(一次性聚合查询,列表页可接受;若过慢再升级为 trace 级列,属实现细节)。

## 5. Fork 导入链路(零改动验证)

Fork 的发起/消费不区分来源:`request_fork` 校验决策点存在 → pending 队列 → 下一次 agent 执行 `acquire_context` 消费 → 前缀 `recorded_point` 读导入的 `output`(形态已对齐插桩器)→ 后缀真调。**唯一约束**:消费方的插桩器产出/回放形态须与导入映射一致(OpenAI/LangChain 两家已对齐,见 §2);设计上不做跨框架形态适配(推迟)。

## 6. 示例与测试

- `examples/react_agent_import_trace.py`(离线,无 API key):① 用 FakeLLM 录一条 3 步链;② 合成扁平 span 导出 JSON(含 1 个 LLM span、1 个 TOOL span、1 个无 kind span);③ 调 import API 导入;④ 对导入 trace step1 发起 Fork 并用第二个 FakeLLM 执行;⑤ 打印回放/真调对比。断言前缀输出来自导入记录、后缀真调。
- 单元(新建 `tests/unit/test_importer.py`):
  - OTLP 信封与扁平两形态等价导入;
  - LLM/TOOL 映射:input_context/output 形态逐字段断言(含 JSON 字符串属性二次解析);
  - 顺序与因果边;未知 kind 忽略并计数;
  - 空映射 / 非 JSON → `ImportError`,不落库;
  - fork 导入 trace:前缀回放不真调、后缀真调(集成测试,复用 `tests/conftest.py` 设施)。
- e2e(`tests/integration/test_server_e2e.py`):`POST /api/traces/import` 全链路 → 列表/详情带 `imported` → 对导入 trace 走 `/api/forks` → 执行 → 分支落库;非法导入 422 不落库。

## 数据流

```
外部导出 JSON ──POST /api/traces/import──▶ importer.import_trace
  → 拍平属性 → span kind 识别(LLM/TOOL)→ 稳定排序 + DFS 定 step_index
  → create_trace_with_root(lifecycle=done, agent_name=service.name)
  → write_decision_point(input_context/output 按 §2 形态, meta.imported=true)
  → publish "trace.imported"
面板: 导入按钮 → 文件 → API → 列表刷新,「导入」徽标;点开 → 正常查看
Fork: request_fork(导入 trace, step N) → 下次 agent 执行消费
      → 前缀 0..N-1 回放导入 output(不真调)→ 后缀 N.. 真调落新分支
```
