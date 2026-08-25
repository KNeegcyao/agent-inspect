# 贡献指南(给人类开发者)

欢迎为 Agent-Inspect 做贡献。本仓库是 **spec-driven** 的——"先对齐规格,后写代码"是硬性要求。这份指南告诉你怎么开始开发、怎么走流程、怎么提交。

> 开发协议与铁律的完整版(给 AI 与人共用)见 [CLAUDE.md](CLAUDE.md);架构形状见 [docs/architecture.md](docs/architecture.md);接口契约见 [docs/contracts.md](docs/contracts.md);测试策略见 [docs/testing.md](docs/testing.md)。

## 1. 开发环境

| 项 | 要求 |
|---|---|
| Python | >= 3.11 |
| Node | >= 20(UI 子项目) |
| 平台 | macOS / Linux 优先;Windows 仓库内嵌服务应可用但非一保证 |

### 安装(Python 侧)
```bash
python -m pip install -e ".[dev]"     # 装本包 + dev 依赖(pytest 等)
```

### 安装(UI 侧)
```bash
cd ui
npm install
npm run dev                  # 起开发服务(改 UI 时用)
npm run build                # 产出构建产物,供进程内服务托管
```

### 第一个跑通(确认环境健康)
```bash
pytest -q ; echo $?          # 期望 0
openspec validate --all       # 期望:1 passed
```

## 2. 开发流程(spec-driven)

一切有意义的改动都从 **OpenSpec change** 开始,不要先动代码。

```
1. 探索   /opsx:explore         需求不清时,先读代码/权衡,不写码
2. 提案   /opsx:propose         生成 openspec/changes/<name>/proposal.md+specs+design+tasks
3. ——人工 review 关卡——        审 proposal 与 spec delta,这是你/审者拍板的关口
4. 实现   /opsx:apply          按 tasks 实现,每完成一项勾 checkbox
5. 归档   /opsx:archive        完工并验证通过后归档,delta 合入主规格
```

CLI 形态(不依赖特定 IDE/skill 时):
```bash
openspec new change "<kebab-name>"
openspec status --change "<name>" --json
openspec instructions <artifact> --change "<name>"
openspec validate --all
openspec archive "<name>" --yes
```

> 补丁式描述性需求、纯 bug 修复、纯文档/工具改动可走轻量路径,但请在提交说明里注明"未走完整 change"的理由。

## 3. 规格书写约定(写 spec 时务必遵守)

- 只描述**可观测行为**;内部类名、库选型、实现步骤写进 `design.md`,**不进 spec**。
- 用 **SHALL**,需求以 `### Requirement:` 起,场景必须 `#### Scenario:`(恰好 4 个井号)、**WHEN/THEN**。
- 每个 Requirement 至少一个 Scenario;无法触发者不入 spec。
- 新建能力 delta 头固定 `## ADDED Requirements`,顺序 `## Purpose`(≥50 字)→ ... 。
- spec 文件内**禁止品牌名**(SQLite/FastAPI/...),只在 `config.yaml#context` 与 design 写。

详见 [CLAUDE.md §2](CLAUDE.md#2-规格书写约定must硬性要求)。

## 4. 怎么加一个新能力(端到端示例)

假设要加"条件断点(Live Mode)":
1. `openspec new change add-live-mode-breakpoints`
2. `openspec instructions proposal --change ...` 取写作规范,起草 `proposal.md`(Why/What/Capabilities/Impact/Out-of-Scope/Open Questions)。
3. `openspec instructions specs --change ...`,在 `specs/live/spec.md` 写 delta(仅可观测行为)。
4. `design.md` 写实现与数据结构、`tasks.md` 拆任务带 checkbox。
5. `openspec validate add-...`;自跑 `pytest` 确认现有用例不回归。
6. 提交,在 PR 描述里贴提案摘要、求 review(spec 是人工关卡)。
7. review 过 → `/opsx:apply` 实现并补测试(见 [docs/testing.md](docs/testing.md)),测试绿。
8. `/opsx:archive` 归档,delta 并入 `openspec/specs/`。

## 5. 分支与提交约定

- **分支名**:`<type>/<kebab-name>`,如 `feat/fork-engine`、`fix/replay-missing-output`、`docs/architecture`。
- **提交**:Conventional Commits。
  ```
  feat: fork 后缀真执行按 branch_from_step 边界
  fix: replay 无记录输出时退回真调而非空回放
  refactor: ...
  docs: ...
  test: ...
  chore: ...
  ```
- **标题**用中文或英文皆可,**祈使句**、一行 ≤72 字符为佳;正文交代 why。

## 6. PR 检查清单(CI 与人工同看)

- [ ] `openspec validate --all` 通过(1 passed)
- [ ] `pytest -q` 全绿;改动核心路径时带 `pytest --cov --cov-branch`
- [ ] 若有 UI 改动:`cd ui && npm ci && npm run build` 绿;UI 测试通过
- [ ] 若有行为改动:**已走 change**(有对应 delta spec),不是只改代码
- [ ] **SPEC 与代码同一次提交**(不允许"先合代码,后补 spec")
- [ ] 关闭/未启用拦截跑既有 LangChain/OpenAI 用例无回归(regression baseline)
- [ ] 不引入 ClickHouse / WASM / 独立后端等 MVP Out-of-Scope 依赖
- [ ] commit message 合 Conventional Commits

## 7. 加分项(让 review 更顺)

- 新增 spec scenario 时,在对应测试 docstring 里回链 `# spec: <capability>.<scenario>`。
- 影响接口契约的改动,同步更新 [docs/contracts.md](docs/contracts.md)。
- 涉及架构边界/目录的改动,同步更新 [docs/architecture.md](docs/architecture.md)。
- 跨进程/真调/fork 副作用相关的改动,在 PR 描述里点明对 [proposal v2](agent-inspect-proposal-v2.md) 风险节的应对。

## 8. 不接受的改动(会直接打回)

- 不带 change 而直接改已归档的 `openspec/specs/**/spec.md`。
- spec 使用品牌名/实现细节(违反"可观测行为"原则)。
- 引入已明确 Out-of-Scope 的依赖(ClickHouse、WASM、IDE SDK、独立 DB server 外置后端)。
- 插桩污染被测框架(破坏"关闭零回归")。

## 9. 行为第一

若本指南与 [CLAUDE.md](CLAUDE.md) 有任何描述性差异,以 CLAUDE.md 与 `openspec/` 为准;本文只是把流程讲给人类听。
