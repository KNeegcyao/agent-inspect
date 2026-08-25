# 能力基线规格 (main specs)

本目录是 Agent-Inspect **当前系统能力的主规格**(单一事实源)。当前为 greenfield:能力基线由进行中的 change `add-agent-inspect-mvp` 提出,待其归档后 delta 并入本目录成为正式基线。

## 能力清单 (MVP 提案,待归档)

| 能力 | 路径 | 对应源码层(预期) | 状态 |
|------|------|-----------|------|
| 决策点拦截与自动插桩 | `interception/spec.md` | `sdk/interceptor/` | 提案(change `add-agent-inspect-mvp`,待归档) |
| 决策点记录与存储 | `recording/spec.md` | `sdk/recorder/`、`server/store/` | 提案(待归档) |
| Counterfactual Fork | `fork/spec.md` | `sdk/interceptor/`、`server/session/` | 提案(待归档) |
| 本地运行时与面板自启 | `local-runtime/spec.md` | `server/`、`sdk/controller/` | 提案(待归档) |
| 单条 Trace 决策视图 | `trace-ui/spec.md` | `ui/TraceView/` | 提案(待归档) |

## 显式不纳入 MVP(后续 change 处理)

Live 活体调试(Mode C)、TS/Go SDK、VSCode/JetBrains 插件、内置 eval 引擎、ClickHouse 后端、WASM 大规模渲染、多 Agent 跨进程追踪。详见 `openspec/config.yaml#context` 与 `changes/add-agent-inspect-mvp/proposal.md`。

## 验收判据(Criteria)在哪

本 schema 不设独立 criteria 文件;每个 **Requirement** 下的每个 **`#### Scenario: <名字>`** 即该需求的验收判据。
状态合计规则:
- 一个 Requirement 的全部 Scenario 通过 → 该 Requirement 满足
- 一个 capability 的全部 Requirement 满足 → 该能力在规格层面达成

## 维护约定

- 只描述可观测行为;内部类名、库选型、实现步骤进 design.md,不进 spec。
- 用 **SHALL** 表述规范要求;需求以 `### Requirement:` 开头,场景必须以 `#### Scenario:`(恰好 4 个井号),用 WHEN/THEN。
- 每一个 Requirement 至少一个 Scenario;无法触发的行为不入 spec。
- 删除/修改需求必须带对应 change,禁止绕过 change 直接改写主规格(待基线归档后生效)。
