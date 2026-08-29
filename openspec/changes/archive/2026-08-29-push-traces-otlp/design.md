# push-traces-otlp Design

## 概述

`agent_inspect/pusher.py` 在 exporter 之上做两件事:把导出信封包装为推送协议的 HTTP+JSON 请求体(ExportTraceServiceRequest 形状),并用标准库 urllib 同步 POST 到用户端点。零新依赖;同步、一次性、可观测;推送不落库、不改本地数据。

## 1. 载荷包装(`agent_inspect/pusher.py`)

`push_trace(store, recorder, trace_id, endpoint, timeout=10.0, branch_id=None) -> PushResult`

- 信封来源:`exporter.export_trace(store, recorder, trace_id, branch_id)`(同一映射,spec「载荷与导出映射一致」由此天然成立;单测逐字段压测)。
- 在信封基础上补推送协议要求的包装:
  - 每个 `scopeSpans` 追加 `"scope": {"name": "agent-inspect"}`(遥测来源声明);
  - 每个 span 追加 `"kind"` 整数字段:LLM span → 3(CLIENT,出站依赖),TOOL span → 1(INTERNAL);
  - `resource`/属性/时间/ID 字段原样(OTLP/JSON 的 traceId/spanId 即 hex 字符串,与导出一致)。
- HTTP:`POST <endpoint>`,`Content-Type: application/json`,`Content-Length` 自动;`urllib.request.urlopen(timeout=timeout)`;非 2xx 抛 `PushError`(含状态码与响应体前 200 字符);`URLError/ConnectionError` 抛 `PushError("endpoint unreachable: ...")`。
- `PushResult(delivered_spans: int, status_code: int, endpoint: str)`;`delivered_spans` = 信封内 span 总数。

## 2. API(`_server/app.py`)

`POST /api/traces/{trace_id}/push`,body:`{"endpoint": str(必填), "timeout": float(可选,默认 10,1..60)}`

- trace 缺失 → 404(与导出端点一致);
- endpoint 缺失/非 http(s) → 422;
- 推送成功 → 200 `{"delivered": n, "endpoint": ..., "status_code": code}`;
- `PushError` → 502 `{"error": str(e)}`(上游送达失败,与既有 422 语义区分)。
- 只读端点:任何分支都不写库。

## 3. UI(`web/`)

- 详情头 `trace-rel-bar` 加「推送」按钮(与「导出」并排):`window.prompt` 填端点(默认值 `http://127.0.0.1:4318/v1/traces`,即推送协议 HTTP 形态的标准端口路径);取消则无动作。
- 结果呈现:成功 → rel-bar 内出现一次性「已送达 ×N」chip(本地 state,下次操作刷新);失败 → 既有 `setError` 错误条。
- api.js 增 `pushTrace(traceId, endpoint, timeout?)`。

## 4. 测试策略(mock 收集端点)

- 单测 `tests/unit/test_pusher.py`:用标准库 `http.server.BaseHTTPRequestHandler` 起线程 mock 端点(临时端口,捕获 method/path/headers/body):
  - 载荷断言:body JSON 解析后 `resourceSpans[0].scopeSpans[0].scope.name == "agent-inspect"`;span kind 字段(LLM=3/TOOL=1);属性与 `export_trace` 同 trace 输出逐字段一致;POST 路径与 Content-Type;
  - 2xx → PushResult 字段;非 2xx → PushError 含状态码;拒绝连接(关闭端口)→ PushError 含 unreachable。
- e2e(test_server_e2e):真实 session → mock 端点 → `POST /api/traces/{id}/push` 200 + delivered;404 路径;不可达端点 → 502。

## 5. 数据流

```
POST /api/traces/{id}/push {"endpoint": "..."}
  → exporter.export_trace(只读解析)→ 载荷包装(scope + kind)
  → urllib POST endpoint (application/json, timeout)
  → 2xx: PushResult → 200 {delivered, endpoint, status_code}
  → PushError: 502 {error};trace 缺失: 404
面板: 详情头「推送」→ 端点输入 → 结果 chip / 错误条
```
