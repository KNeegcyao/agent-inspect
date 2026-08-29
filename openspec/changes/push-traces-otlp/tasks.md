# push-traces-otlp Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:推送的 why / 载荷包装 / 错误语义 / 范围
- [x] 1.2 `specs/trace-push/spec.md` delta:3 requirement(推送映射与送达 / 失败可观测 / 面板入口)共 5 场景

## 2. 后端推送器

- [x] 2.1 新建 `agent_inspect/pusher.py`:信封 → 推送载荷(scope 声明 + span kind:LLM=CLIENT/TOOL=INTERNAL),urllib POST(application/json,timeout),只读不落库
- [x] 2.2 `PushResult(delivered_spans, status_code, endpoint)`;非 2xx / 不可达 → `PushError`(含状态码或 unreachable 原因)

## 3. API 与 UI

- [ ] 3.1 `POST /api/traces/{trace_id}/push`:endpoint/timeout 校验,成功 200 回报 delivered;trace 缺失 404;PushError 502
- [ ] 3.2 `web/src/api.js` 增 `pushTrace`;App.jsx 详情头「推送」按钮(prompt 端点,默认 4318 路径);成功「已送达 ×N」chip,失败错误条

## 4. 测试

- [x] 4.1 单测(mock 收集端点):载荷与导出映射逐字段一致 + scope/kind;送达统计;非 2xx / 不可达错误;只读无写入
- [ ] 4.2 e2e:推送接口全链路(mock 端点)200/404/502
- [ ] 4.3 全量 pytest 通过(含导入/导出零回归);确认零新增第三方依赖

## 5. 验证与发布

- [ ] 5.1 `openspec validate --all` 通过
- [ ] 5.2 `cd web && npm run build` 通过
- [ ] 5.3 README「导入导出」一节扩为含推送;`openspec/specs/README.md` 能力清单随 archive 更新
- [ ] 5.4 `openspec archive push-traces-otlp --yes`;commit + push
