# Agent-Inspect 开发约定

> 仓库:https://github.com/KNeegcyao/agent-inspect
> 本文档是本仓库的**强制开发协议**。任何 agent(含 Claude Code)和任何人类在此仓库内工作都必须先读这里。
> 产物形态:开源 AI Agent 交互式调试器(Python SDK + 本地内嵌服务 + 单页 React UI)。烟雾幕:不是 observability 平台,对标 Chrome DevTools / pdb,见 [README](README.md) 与 [docs/product.md](docs/product.md)。

## 1. 开发标准流程:Spec-Driven(MUST,硬性要求)

本项目把 **OpenSpec** 定为需求的唯一事实流程。**"先对齐规格,后写代码"是硬性要求,不是建议。**

### 铁律(HARD RULES)

1. **任何有意义的 feature 必须先有 change**:创建并完成 OpenSpec change(`proposal → specs → design → tasks`),通过人工 review 关卡后才动代码。补丁式描述性需求、纯 bug 修复、纯文档/工具改动可走轻量路径,但需在提交说明里注明。
2. **Human gate 在 spec,不在代码**:需人工审的是 `openspec/changes/<name>/proposal.md` 与 `specs/` 的 delta spec(Markdown)。review 过关后才进入 apply。
3. **spec 是唯一事实源**:需求只存于 `openspec/specs/`(基线,待首个 change 归档后生成)与进行中的 `openspec/changes/`。不得把隐藏需求塞进对话历史或代码注释。**改行为 = 改 spec**。
4. **严禁绕过 change 直接改写已归档的主规格** `openspec/specs/**/spec.md`。改动必须带 change,archive 时由工具合并。
5. **prose 与 spec 冲突时以 spec 为准**:README / docs/* 只解释 *why*,行为以 spec 为准。改行为必须改 spec,不走 prose。

### 流程口令(Claude Code skill `/opsx:*`,等价于下列 CLI)

```
/opsx:explore   需求不明确时先做思考伴侣(读代码/权衡方案,先不写码)
/opsx:propose   生成 openspec/changes/<name>/(proposal/specs/design/tasks)
（人工 review 关卡)审 proposal 与 spec,通过后再继续
/opsx:apply     按 tasks 实现,每完成一项勾选 checkbox
/opsx:sync      把 delta spec 同步到主规格(不归档时)
/opsx:archive   完成并归档,delta 合入主规格
```

### 命令(CLI,跨工具通用)

```bash
openspec new change "<kebab-name>"            # 建 change
openspec status --change "<name>" --json     # 查 artifact 构建顺序/完成度
openspec instructions <artifact> --change "<name>"  # 取该 artifact 写作规范
openspec validate --all                      # 校验 specs + changes
openspec show "<name>"                        # 看提案
openspec archive "<name>" --yes               # 归档并更新主规格
```

## 2. 规格书写约定(MUST)

- 只描述**可观测行为**;内部类名、库选型、实现步骤进 `design.md`,**不进 spec**。
- 用 **SHALL**(规范);需求以 `### Requirement:` 开头,场景必须以 `#### Scenario:`(恰好 4 个井号),用 **WHEN/THEN**。
- 每个 Requirement **MUST** 至少一个 Scenario;无法触发的行为不入 spec。
- 新建能力 delta spec 头固定 `## ADDED Requirements`;顺序:`## Purpose`(≥50 字符)→ `## ADDED Requirements` → `### Requirement:` → `#### Scenario:`。
- spec 文件内**禁止出现实现品牌名**(SQLite / FastAPI / WebSocket / contextvars / OpenInference 等),这些只允许出现在 `openspec/config.yaml#context` 与 `design.md`。spec 只写可观测行为。

## 3. 工程约束(不可漂移)

### 运行时与语言
- **Python >= 3.11**(SDK + 内嵌服务);**Node >= 20**(仅 UI 子项目);UI 用 ESM + TypeScript。
- Python 包以 `agent_inspect` 为导入名(`import agent_inspect`),仓库根布局(详见 [docs/architecture.md](docs/architecture.md#6-mvp-目录骨架直接照抄开发))。
- **不引入**:ClickHouse、WASM、任何独立 DB server 外置后端。MVP 仅本地单文件存储、进程内嵌服务。
- 依赖最小化:Python 标准库优先;Runtime 依赖见 [docs/architecture.md](docs/architecture.md#7-依赖矩阵mvp)。

### 架构不变量(违反即返工)
- **Interceptor 是地基**:LLM 调用与工具调用统一包成"先登记决策点 → 按模式路由真调与否"。Replay/Fork/(后续)Live 是同一拦截器的三种行为,**不是三套实现**。
- **决策结构是森林/DAG**,非父子树;决策点间存显式因果边(`agent.step.cause`),不止 parent-child。
- **链路传播用 contextvars**(trace_id/branch_id/mode/replay_cursor/branch_from_step),贯穿 async;不引入全局可变单例。
- **已完成登记即落盘**(崩溃不丢已完成者);多分支并发写入串行落盘、互不损坏。
- **Fork 默认真执行**且 UI 明示;提供 `dry_run` 只读预览。副作用沙箱是 Phase 2,不入 MVP。
- **站 OpenInference 语义**,不另造 OTel Agent 语义。

## 4. 现状口径(baseline)

- 项目状态:**greenfield / spec-complete**,首个 change `add-agent-inspect-mvp` 待 apply。
- MVP 5 能力:`interception` / `recording` / `fork` / `local-runtime` / `trace-ui`(30 req / 69 scenario,见 `openspec/specs/README.md`)。
- 插桩覆盖:**LangChain + OpenAI SDK** 两家(conventional `chat.completions.create`)。其余框架/语言推迟。
- 存储与后端:本地单文件.SQLite,进程内嵌 FastAPI。无 server 启动命令,一行 `agent_inspect.start()`。
- 许可:**Apache-2.0**。
- 详细 SME 上下文见 `openspec/config.yaml#context`(AI 起草 spec 时的基准,务必精确)。

## 5. 开发环境与验证(MUST 跑绿才能说"完成")

```bash
# Python 侧
python -m pip install -e ".[dev]"
pytest -q                         # 全量测试,绿才能提交

# UI 侧
cd ui && npm install && npm run build   # 或 npm run dev 起开发服务

# 规格侧
openspec validate --all            # 必须 1 passed
```

改完代码**必须全量跑测试**确认无回归,且**SPEC 与代码同一次提交**。
关闭拦截跑既有 LangChain/OpenAI 用例必须零回归(这是 `interception.关闭零回归` 的硬验收)。

## 6. 开发期目录约定(MVP,见 architecture 详图)

```
agent-inspect/
├── agent_inspect/        # Python 包:interceptor/ recorder/ controller/ _server/{store,session,api}
├── ui/                   # React 单页(npm 子项目)
├── tests/                # 对应三测
├── docs/                 # architecture / contracts / testing / product
├── openspec/             # spec 事实源(config + specs + changes)
├── pyproject.toml
└── README.md
```

## 7. 与各文档分工(勿重复劳动)

| 文档 | 给谁 | 说什么 |
|---|---|---|
| 本文件 | AI & 协议遵守者 | 铁律/流程/约束/环境/口径 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 人类贡献者 | 怎么加入开发、流程体验、PR 规范 |
| [docs/architecture.md](docs/architecture.md) | 任何要放代码的人 | 形状:组件/数据模型/目录树/部署 |
| [docs/contracts.md](docs/contracts.md) | 前后端对接 | 契约:schema/HTTP/WS/start() 签名 |
| [docs/testing.md](docs/testing.md) | 写测试的人 | 三测怎么搭、69 scenario 怎么映射 |
| [docs/product.md](docs/product.md) | 想懂定位的人 | 痛点/定位/三态/旗舰/roadmap |

行为以 `openspec/` 为准;以上文档只解释 *why* 与 *how-to-build*,不重复定义行为。
