# node-import-push Design

## 概述

Python `importer.py` / `pusher.py` 的 TS 同构移植。Node 端存储全量内联(无增量快照/去重),导入落库直接 `store.writeDecisionPoint`,与 Node 自录同构。推送用全局 `fetch` + `AbortSignal.timeout`(Node 20+,零依赖)。

## 1. 导入器(`sdks/node/src/importer.ts`)

- `importTrace(store, payload): ImportResult {traceId, rootBranchId, decisionPoints, skipped}`;失败抛 `TraceImportError`;
- 两形态:`resourceSpans[].scopeSpans[].spans[]`(OTLP 信封,属性数组拍平)与 `{spans: [...], agent_name?}`(扁平);
- 识别 `openinference.span.kind`:LLM/TOOL → 决策点,其余忽略计数;JSON 字符串属性(`llm.input_messages`/`llm.output_messages`/`llm.invocation_parameters`/`tool.parameters`/`tool.return_value`)二次解析,扁平点分键(`llm.input_messages.0.message.role`)兼容;
- 顺序:父 span 建树 + DFS(稳序 start/spanId);`step_index` = 遍历序;`cause_edge` 线性链;
- 映射:LLM 输出 `{content, tool_calls}`(tool_calls 透传)、工具 `{tool, args}`/`{result, is_error}`——与 Node 插桩器 `shape` 同形;
- trace 头:`agent_name`(service.name/agent_name,缺省 "imported")、`lifecycle=done`、`started_at` = 最早 span 起始(秒,数量级启发);`meta.imported = true`;
- 空映射抛 `TraceImportError`,不落库。

## 2. 推送器(`sdks/node/src/pusher.ts`)

- `pushTrace(store, traceId, endpoint, timeoutMs=10000): PushResult {delivered, statusCode, endpoint}`;trace 缺失抛 `PushError`;
- 载荷 = `exportTrace(...)` 信封 + `scope: {name: "agent-inspect"}` + span kind(LLM→3/TOOL→1);
- `fetch(endpoint, {method: POST, body, signal: AbortSignal.timeout(timeoutMs)})`;非 2xx/网络错误 → `PushError`(含状态码或原因);只读不落库。

## 3. 端点(`server.ts`)

- `POST /api/traces/import`:非 JSON/非法 → 422;成功 200 `{trace_id, decision_points, skipped}` + SSE `trace.imported`;
- `POST /api/traces/{id}/push`:body `{endpoint, timeoutMs?}`;404/422/502 同 Python 语义。

## 4. 测试

- 单测(`tests/importer.test.ts`):两形态等价、逐字段映射、顺序与因果、忽略计数、空映射拒绝、往返(导出 → 导入内容一致);
- 单测(`tests/pusher.test.ts`):mock 收集端(local http)载荷断言(scope/kind/属性)、送达统计、非 2xx、不可达;
- e2e(`tests/import-push.test.ts`):`POST /api/traces/import` → 列表/决策点可查 → Fork 可用;`POST .../push` 到 mock 收集端 200;404/422/502 路径。
