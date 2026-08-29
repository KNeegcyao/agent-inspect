# import-openinference-traces Tasks

## 1. OpenSpec 文档

- [ ] 1.1 `proposal.md` / `design.md`:外部 span 导出导入的 why / 接受形态 / 映射规则 / 范围
- [ ] 1.2 `specs/trace-import/spec.md` delta:3 requirement(导入映射 / 参与调试流 / 非法拒绝)共 8 场景

## 2. 后端导入器

- [ ] 2.1 新建 `agent_inspect/importer.py`:属性拍平(OTel 数组形态 / 扁平对象)、OpenInference 结构化属性 JSON 字符串二次解析
- [ ] 2.2 OTLP JSON 信封与扁平 span 列表两种形态解析;span 识别(`openinference.span.kind`:LLM/TOOL,其余忽略计数)
- [ ] 2.3 稳定排序 + 深度优先遍历定 step_index;cause_edge 线性链;trace 头(service.name / lifecycle=done / started_at)
- [ ] 2.4 LLM 映射:`input_context={messages, model, params}`、`output={"content", "tool_calls"}`(与插桩器同形);TOOL 映射:`{"tool", "args"}` / `{"result"}`
- [ ] 2.5 落库复用既有 `create_trace_with_root` + `write_decision_point`;`meta.imported` + `meta.latency_ms`;空映射抛 `ImportError` 不落库

## 3. API 与 UI

- [ ] 3.1 `POST /api/traces/import`:合法导入返回 trace_id/计数,`ImportError` → 422 + 可观测原因;发布 `trace.imported` 事件
- [ ] 3.2 trace 详情/列表响应增加 `imported` 标记(聚合决策点 meta)
- [ ] 3.3 `web/src/api.js` 增 `importTraces(payload)`;App.jsx 加「导入」按钮 + 文件选择 + 失败错误条
- [ ] 3.4 「导入」徽标(trace 列表项 + 详情头),样式复用既有徽标风格

## 4. 测试

- [ ] 4.1 单元:两形态等价;LLM/TOOL 映射逐字段(含 JSON 字符串属性二次解析);顺序与因果边;未知 kind 忽略计数
- [ ] 4.2 单元:空映射 / 非 JSON → `ImportError`,store 无新 trace(不落库)
- [ ] 4.3 集成:fork 导入 trace → 前缀回放不真调、后缀真调落新分支
- [ ] 4.4 e2e:`POST /api/traces/import` 全链路 → `imported` 标记 → `/api/forks` → 执行;非法导入 422 不落库
- [ ] 4.5 全量 pytest 通过(既有能力零回归)

## 5. 验证与发布

- [ ] 5.1 `openspec validate --all` 通过
- [ ] 5.2 `cd web && npm run build` 通过
- [ ] 5.3 离线示例 `examples/react_agent_import_trace.py` 跑通(合成导出 → 导入 → Fork → 对比输出)
- [ ] 5.4 README 增补「导入外部链路」一节 + `openspec/specs/README.md` 能力清单随 archive 更新
- [ ] 5.5 `openspec archive import-openinference-traces --yes`;commit + push
