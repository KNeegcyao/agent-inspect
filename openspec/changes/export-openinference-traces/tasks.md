# export-openinference-traces Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:导出的 why / 形态契约 / 逆映射规则 / 范围
- [x] 1.2 `specs/trace-export/spec.md` delta:3 requirement(导出映射 / 往返等价 / 导出入口)共 4 场景

## 2. 后端导出器

- [x] 2.1 新建 `agent_inspect/exporter.py`:`export_trace(store, recorder, trace_id, branch_id=None)` 读路径全量解析(resolve_dp),无写入
- [x] 2.2 决策点 → span 逆映射:LLM(input_messages/output_messages/invocation_parameters JSON 字符串,含 tool_calls)/ TOOL(name/parameters/return_value)
- [x] 2.3 span 父子链(因果边线性链)、时间合成(started_at 基 + latency)、OTLP 信封组装(service.name / traceId / spanId)

## 3. API 与 UI

- [x] 3.1 `GET /api/traces/{trace_id}/export`:合法导出附件下载(Content-Disposition);trace 不存在 404;空链返回空 spans 信封
- [x] 3.2 `web/src/api.js` 增 `exportTraceUrl(traceId)`;App.jsx 详情头加「导出」按钮(window.open 下载)

## 4. 测试

- [x] 4.1 单测:LLM/工具逐字段导出;顺序与父子链;空链;往返等价(导出 → 导入 → kind/顺序/输入输出逐一一致)
- [x] 4.2 e2e:导出接口(下载头/往返经真实 HTTP/404)
- [ ] 4.3 全量 pytest 通过(既有能力含导入零回归)

## 5. 验证与发布

- [ ] 5.1 `openspec validate --all` 通过
- [ ] 5.2 `cd web && npm run build` 通过
- [ ] 5.3 示例脚本追加「导出 → 再导入」往返演示并跑通
- [ ] 5.4 README 导入一节扩为「导入导出」;`openspec/specs/README.md` 能力清单随 archive 更新
- [ ] 5.5 `openspec archive export-openinference-traces --yes`;commit + push
