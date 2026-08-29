# export-openinference-traces Design

## 概述

`agent_inspect/exporter.py` 提供只读的逆映射:trace 决策链 → span 导出 JSON。与导入器(importer.py)共享同一契约,互为逆操作;往返等价是本 change 的核心验收,也是导入器持续回归的免费校验器。不碰拦截器 / 记录路径 / 存储。

## 1. 导出形态(`agent_inspect/exporter.py`)

`export_trace(store, recorder, trace_id, branch_id=None) -> dict`

- **OTLP JSON 信封**(与导入端同契约):

```json
{
  "resourceSpans": [{
    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "<agent_name>"}}]},
    "scopeSpans": [{"spans": [...]}]
  }]
}
```

- trace 元数据:`agent_name` → `service.name`。OTel `traceId`(32 hex)用 trace.id 的 uuid 段补齐生成,`spanId`(16 hex)用确定性生成(`sp<step>` 语义放 name,hex 由 uuid 派生)——往返测试断言内容等价,不断言 id 相等。
- 分支选择:默认 root 分支(`trace.root_branch_id`);`branch_id` 显式指定时导出该分支链(fork 分支的注入结果随之导出)。

## 2. 决策点 → span 逆映射(与 importer._dp_from_span 严格对偶)

| 决策点 | span | 属性 |
|---|---|---|
| `kind=llm` | `openinference.span.kind=LLM`,`name=agent_id` | `llm.model_name=<input.model>`;`llm.input_messages` = JSON 字符串 `[{"message": {role, content}}]`(消息含 `tool_calls` 时一并入内);`llm.output_messages` = JSON 字符串(assistant 输出,content + tool_calls);`llm.invocation_parameters` = JSON 字符串(input.params,空则省略) |
| `kind=tool` | `TOOL`,`name=agent_id` | `tool.name=<input.tool>`;`tool.parameters` = JSON 字符串(input.args);`tool.return_value` = JSON 字符串(output.result);`tool.is_error`(仅当 True) |

- **父子链**:决策点因果边为线性链 → span `parentSpanId` 逐级指向前一 span(与导入端 DFS 遍历序一致,往返后顺序稳定)。
- **时间**:`startTimeUnixNano` 以 `trace.started_at` 为基、每步 +1ms 递增;`endTimeUnixNano = start + meta.latency_ms`(缺省 1ms)。纳秒整数转字符串(OTLP JSON 惯例)。
- 输入输出经 `recorder.serializer.resolve_dp` 全量解析(diff/blob 引用先还原),导出文件自包含。

## 3. API(`_server/app.py`)

`GET /api/traces/{trace_id}/export`

- trace 缺失 → 404 `{"error": "trace not found"}`(与既有详情端点一致)。
- 响应:`Response(content=json.dumps(...), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{agent_name}-{trace_id[-8:]}.json"'})`——浏览器直接下载,UI 无需额外处理文件名。
- 空链 trace:合法信封、空 spans 数组(spec「空链导出」)。

## 4. UI(`web/`)

- 详情头(`trace-rel-bar`)加「导出」按钮:点击 `window.open(`${base}/api/traces/{id}/export`)`(浏览器接管下载,`Content-Disposition` 已带文件名),不引入下载库。
- api.js 增 `exportTraceUrl(traceId)` 返回地址(纯 URL 拼接)。

## 5. 往返等价校验(测试策略)

单测 `test_roundtrip`:录制(或合成)一段链路 → `export_trace` → `import_trace` → 逐项断言新 trace 决策点的 kind / step_index / input_context / output 与原链路一致。e2e:真实 HTTP `GET /export` → `POST /import` 同样断言 + 404 路径。导入侧属性解析(JSON 字符串二次解析、扁平键)已有覆盖,往返测试反向压测。

## 6. 示例与任务

- 扩展 `examples/react_agent_import_trace.py`:第 4 步导入成功后再对该导入 trace 调 `GET /export`,打印往返字节量与决策点数(演示闭环,不断言)。
- 单测(新建 `tests/unit/test_exporter.py`):LLM/工具逐字段、因果链与顺序、空链、往返等价;e2e(test_server_e2e):导出下载头 / 往返 / 404。

## 数据流

```
GET /api/traces/{id}/export
  → store.get_trace / list_branches(root)
  → recorder.read_branch_points(root)(全量解析)
  → exporter.export_trace:dp → span(属性 JSON 字符串化,父子链,时间合成)
  → OTLP 信封 dict → 附件下载
POST /api/traces/import(同文件)
  → importer.import_trace:span → dp → 新 trace(内容等价)
```
