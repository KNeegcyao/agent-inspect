# 能力基线规格 (main specs)

本目录是 Agent-Inspect **当前系统能力的主规格**(单一事实源)。MVP change `add-agent-inspect-mvp`、Live 活体调试 change `add-live-debug-mode-c` 与分支并排 diff change `add-branch-diff` 均已归档,其 delta 已并入本目录成为正式基线。

## 能力清单 (已并入基线)

| 能力 | 路径 | 对应源码层(预期) | 状态 |
|------|------|-----------|------|
| 决策点拦截与自动插桩 | `interception/spec.md` | `sdk/interceptor/` | 基线(change `add-agent-inspect-mvp`,已归档) |
| 流式调用插桩 | `interception/spec.md`(流式能力) | `interceptor/streaming.py`、`openai_patcher.py` | 基线(change `python-streaming-instrumentation`,已归档) |
| 插桩模块开关 | `interception/spec.md`(开关能力) | `session.py` | 基线(change `instrument-switch`,已归档) |
| 决策点记录与存储 | `recording/spec.md` | `sdk/recorder/`、`server/store/` | 基线(已归档) |
| Counterfactual Fork | `fork/spec.md` | `sdk/interceptor/`、`server/session/` | 基线(已归档) |
| 本地运行时与面板自启 | `local-runtime/spec.md` | `server/`、`sdk/controller/` | 基线(已归档) |
| 单条 Trace 决策视图 | `trace-ui/spec.md` | `ui/TraceView/` | 基线(已归档) |
| Live 活体调试(Mode C) | `live-debug/spec.md` | `interceptor/`、`debug.py` | 基线(change `add-live-debug-mode-c`,已归档) |
| 分支并排 diff | `branch-diff/spec.md` | `diff.py`、`_server/app.py`、`web/` | 基线(change `add-branch-diff`,已归档) |
| 跨 trace 对比 | `branch-diff/spec.md`(跨 trace 能力) | `_server/app.py`(全局分支索引/跨 trace diff)、`web/`(按 trace 分组) | 基线(change `compare-traces`,已归档) |
| 外部链路导入 | `trace-import/spec.md` | `importer.py`、`_server/app.py`、`web/` | 基线(change `import-openinference-traces`,已归档) |
| 外部链路导出 | `trace-export/spec.md` | `exporter.py`、`_server/app.py`、`web/` | 基线(change `export-openinference-traces`,已归档) |
| 外部链路推送 | `trace-push/spec.md` | `pusher.py`、`_server/app.py`、`web/` | 基线(change `push-traces-otlp`,已归档) |
| JS 运行时 SDK | `js-sdk/spec.md` | `sdks/node/`(TypeScript,同契约子集 + 面板复用) | 基线(change `add-js-sdk`,已归档) |
| 决策点搜索 | `trace-search/spec.md` | `search.py`、`_server/app.py`、`web/` | 基线(change `search-decision-points`,已归档) |
| 跨 trace 全局搜索 | `trace-search/spec.md`(全局能力) | `_server/app.py`、`web/` 侧栏 | 基线(change `global-search`,已归档) |
| 面板主题切换 | `trace-ui/spec.md`(主题能力) | `web/`(调色板/画布变量/持久化) | 基线(change `panel-theme-toggle`,已归档) |
| JS 运行时 Live 调试 | `js-sdk/spec.md`(Live 能力) | `sdks/node/`(debug.ts/端点/断点持久化) | 基线(change `node-live-debug`,已归档) |
| JS 运行时副作用沙箱 | `js-sdk/spec.md`(沙箱能力) | `sdks/node/`(fork.ts/interceptor.ts) | 基线(change `node-side-effect-sandbox`,已归档) |

## 显式不纳入 MVP 基线(后续 change 处理)

TS/Go SDK、VSCode/JetBrains 插件、内置 eval 引擎、ClickHouse 后端、WASM 大规模渲染、多 Agent 跨进程追踪。Live 活体调试(Mode C)已实现并归档,不再属推迟项。详见 `openspec/config.yaml#context` 与 `openspec/changes/archive/2026-08-27-add-agent-inspect-mvp/proposal.md`。

## 验收判据(Criteria)在哪

本 schema 不设独立 criteria 文件;每个 **Requirement** 下的每个 **`#### Scenario: <名字>`** 即该需求的验收判据。
状态合计规则:
- 一个 Requirement 的全部 Scenario 通过 → 该 Requirement 满足
- 一个 capability 的全部 Requirement 满足 → 该能力在规格层面达成

## 维护约定

- 只描述可观测行为;内部类名、库选型、实现步骤进 design.md,不进 spec。
- 用 **SHALL** 表述规范要求;需求以 `### Requirement:` 开头,场景必须以 `#### Scenario:`(恰好 4 个井号),用 WHEN/THEN。
- 每一个 Requirement 至少一个 Scenario;无法触发的行为不入 spec。
- 删除/修改需求必须带对应 change,禁止绕过 change 直接改写主规格。
