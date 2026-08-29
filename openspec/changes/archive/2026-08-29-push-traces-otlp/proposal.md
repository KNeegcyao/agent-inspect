# push-traces-otlp

## Why

「OpenInference 导入导出」闭环之后,链路的**流动**还差最后一公里:文件能带走,但用户现有的观测栈(Collector / Jaeger / Tempo 等)是常驻服务,期望的是**标准推送协议**把 span 送到端点,而不是手工搬运文件。

本 change 补上推送这半步:把一条 trace 的决策链(经既有 exporter 映射)包装为标准 span 推送载荷,POST 到用户指定的收集端点。工程上刻意保守——**只做推送协议的 HTTP+JSON 形态,标准库实现,零新依赖**,不碰 gRPC/protobuf 二进制(那需要引入依赖,违反"依赖最小化"铁律);不引入后台批量/重试队列(每次推送同步、可观测)。

这是 Phase 3「可选导出到任意 OTel 后端」的最小完整实现:面板填一个端点地址,链路即出现在用户已有的观测世界里。

## What Changes

- **后端(新增 `agent_inspect/pusher.py`)**:
  - `push_trace(store, recorder, trace_id, endpoint, timeout=10.0, branch_id=None)`:复用 `exporter.export_trace` 的 span 映射,包装为推送载荷(`resourceSpans` + scope 声明 + span kind 字段),以 `application/json` POST 到端点;
  - 端点 2xx → 返回送达统计(span 数 + 端点响应状态);不可达 / 非 2xx → 抛可观测错误(含状态码与原因片段);**推送是只读操作**,不改变本地任何数据。
- **API**:`POST /api/traces/{trace_id}/push`(body: `{"endpoint": "...", "timeout": 可选}`)→ 200 送达统计;trace 缺失 404;端点错误 502 + 可观测原因。
- **UI**:详情头「推送」按钮 → 填端点地址(默认 `http://127.0.0.1:4318/v1/traces`)→ 发起推送,成功显示「已送达 ×N」,失败走既有错误条。
- **spec**:新增 `trace-push` 能力(推送映射与送达 / 结果可观测与错误路径 / 面板入口)。
- **测试**:推送载荷与导出映射一致的单测、本地 mock 收集端点(标准库 http.server)的送达/失败/不可达单测、推送 API e2e。

## Out of scope

- 推送协议的 gRPC/protobuf 二进制形态(需引入依赖;HTTP+JSON 是同协议的合法形态,Collector 全系支持)。
- 端点鉴权头、mTLS、批量多 trace 推送、后台自动推送(录制即推送)、重试与离线缓冲队列。
- 推送结果的远端查询/校验(端点返回 2xx 即视为送达;远端如何呈现属观测栈自身职责)。

## Criteria

- 提供端点地址发起推送后,trace 决策链以与导出文件相同的 span 映射送达端点(载荷中每个决策点对应一个 span,属性可读回完整输入输出)。
- 端点 2xx 时回报送达的 span 数与端点状态;不可达或非 2xx 时给出可观测错误,且本地数据不被改动。
- 面板可对任一 trace 填入端点发起推送并看到结果;trace 不存在 404。
- 全量测试通过;既有能力(导入/导出)零回归;不新增任何第三方依赖。
