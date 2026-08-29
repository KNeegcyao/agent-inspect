# export-openinference-traces

## Why

上一个 change 打通了「吃进来」:外部 span 导出可以导入为可调试、可 Fork 的 trace。但互操作是双向的——roadmap 里「OpenInference 导入导出」是一个整体,导出这半边至今缺失:

- 调试者用 Agent-Inspect 修好一段执行后,**没有便携的方式把它交给别人**:给同事复现、给观测平台归档、写进 issue 附件,都得靠口头描述或截图。
- 导入端已经定义并稳定了接受契约;补上导出后,Agent-Inspect 自己的链路也成了这个契约的生产者——**导出 → 导入往返**成为可验证的闭环,也是导入器回归测试的最强校验器。

本 change 是导入的严格对称半边:把一条已记录(或已导入)trace 的决策链映射为遵循 OpenInference 语义约定的 span 导出 JSON。不做导出推送、不做批量、不改存储。

## What Changes

- **后端(新增 `agent_inspect/exporter.py`)**:把一条 trace 的某条分支(默认根分支)决策链导出为 span 导出 JSON(OTLP JSON 信封形态,与导入端同契约):
  - `llm` 决策点 → `openinference.span.kind=LLM` span:完整输入(messages/model/params)与输出(content/tool_calls)映射为对应属性;
  - `tool` 决策点 → `TOOL` span:工具名、参数、返回值映射为对应属性;
  - 因果边线性链 → span 父子链;决策点顺序 → span 树遍历序;`meta.latency_ms` → span 时长。
- **API**:`GET /api/traces/{trace_id}/export` 返回导出 JSON(附件下载);trace 不存在 404。
- **UI**:trace 详情头加「导出」按钮 → 下载 `{agent_name}-{短 id}.json`。
- **往返等价**:导出产物可被导入端原样消费,重建出 kind/顺序/输入输出一致的链路(同时是导入器的回归校验)。
- **spec**:新增 `trace-export` 能力(导出映射 / 往返等价 / 错误路径)。
- **测试**:导出映射单测(LLM/工具逐字段、因果链、空链)、往返等价单测、导出 API e2e(含 404);扩展示例脚本演示「导出 → 再导入」。

## Out of scope

- OTLP/gRPC 推送、watch 目录、多 trace 批量导出打包(zip/tar)。
- 非 JSON 格式(ProtoBuf)。
- 导出导入轨迹之外的派生物(分支 diff 报告、沙箱标记等 meta 不参与互操作契约,保留为决策点 meta 的可选透传之外物)。

## Criteria

- `GET /api/traces/{id}/export` 返回合法 span 导出 JSON:每个决策点一个对应 span,顺序与链路一致,LLM/工具决策点的完整输入输出可在属性中读回。
- 导出文件经 `POST /api/traces/import` 导入后,新 trace 的决策点 kind、顺序、输入输出与原链路一致(往返等价)。
- 面板可对任一 trace 一键导出为 `.json` 文件;trace 不存在时 404。
- 全量测试通过;既有能力(含导入)零回归。
