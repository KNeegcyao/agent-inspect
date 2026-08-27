# Agent-Inspect 并排分支 diff — 设计

## Context

见 `proposal.md`「Why」与 `openspec/config.yaml#context`(SME):Fork 的传播爆点是"同树两分支并排,看世界怎么分叉";MVP 与 Live 已能产生多分支,但对照停留在"前端两列画布 + 输出序列化比对的步骤集合",给不出字段级明细。本 change 增加后端只读 diff 引擎与面板差异详情,把"并排"升级为精确 diff。约束延续:Python-only、本地内嵌服务、本地存储、只读计算不落库、spec 不写实现细节。本文件承载**内部实现**(类名/数据结构/接线步骤),不进 spec。

## Goals / Non-Goals

- 目标:两分支按步骤对齐 → 每步状态(相同/差异/仅左/仅右)→ 差异步骤字段级明细(输入+输出)→ 汇总计数;面板并排着色 + 选中差异步骤展示明细。
- 非目标:工具返回值注入、大上下文增量快照、跨分支写回、语义级 diff、因果边拓扑 diff —— 见 proposal Out of Scope。

## Design Overview

diff 是**纯只读计算**:把两分支各自构造成完整决策链(镜像前端 `chain.js` 的共享前缀递归),按步骤索引对齐,逐步骤判定状态;差异步骤递归展开字段级路径差异。结果经只读接口给面板,面板把每步状态注入两列画布并渲染差异明细。

```
面板选中 主分支 A + 对比分支 B
  └─ GET /api/branches/{A}/diff/{B}
       ① build_chain(A) / build_chain(B)   ← 各自完整链(共享前缀 + 本分支后缀)
       ② diff_chains(chainA, chainB)        ← 按 step_index 对齐
            - 仅一侧 → only_left / only_right
            - 同号同输出 → same
            - 同号异输出 → diff(字段明细)
       ③ summarize → {same, diff, only_left, only_right}
  └─ 面板:两列画布按 per-step 状态着色;选中 diff 步骤 → DiffPanel 展示字段明细
```

## Components

### diff 引擎(`agent_inspect/diff.py`)
- 职责:完整链路构造、步骤对齐、字段级 diff、汇总。纯函数,无 IO 依赖(链路构造除外)。
- 实现:
  - `build_chain(store, serializer, context_snap, branch_id, upto=MAX)` — 镜像前端 `chainSteps`:沿 `parent_branch_id` 递归取前缀(`branch_from_step` 内步骤,标记 inherited),再拼本分支后缀。用既有 `store.get_branch` / `store.get_decision_points` + `serializer.resolve_dp`。
  - `diff_chains(left, right) -> list[StepDiff]` — 以 `step_index` 为键对齐两个链;仅一侧 → `only_*`;双侧同输出 → `same`;双侧异输出 → `diff` + `diff_fields`。
  - `diff_fields(a, b, prefix, depth)` — 递归 JSON 结构 diff,叶子条目 `{path, left, right, status}`;`path` 形如 `output.content` / `input_context.messages[1].content`;仅一侧 → `added`/`removed`;类型或值不同 → `changed`;深度上限防大 prompt 递归爆炸。
- 备选:复用前端 JS 算法后移——被否,后端需字段明细且要单测,e2e 才可观测。

### 只读接口(`agent_inspect/_server/app.py`)
- 职责:暴露 diff 服务给面板。
- 实现:`GET /api/branches/{branch_a}/diff/{branch_b}` → `{branch_a, branch_b, steps:[{step_index, status, kind, agent_id, fields:[{path, left, right, status}]}], summary:{same, diff, only_left, only_right}}`;分支不存在 → 404;两分支非同 trace → 422(可观测原因)。

### UI(`web/`)
- `api.js`:`branchDiff(a, b)` 客户端。
- `App.jsx`:active + compare 均选中时请求 diff,得 `diffByStep`(step_index → status);以该结果**替换**原 `divergentSteps` 推导(单一事实源),注入两列 `ChainCanvas`;selected 命中 diff 步骤时在 inspector 渲染 `DiffPanel`(字段级明细)。
- `ChainCanvas.jsx`:新增 `diffStatus` prop(step_index → status),节点描边按状态着色:same=默认、diff=rose、only_left=amber、only_right=blue,保留 inherited 虚线。
- `styles.css`:diff 面板、字段行(左/右/仅侧)、节点状态色。

## Data Model

- **无新表、无落库**:diff 是只读计算,输入即两分支的既有决策点(经 `resolve_dp` 解析完整)。与 fork/live 的持久化职责不同。
- **对齐键**:`step_index`(两分支共享前缀同号)。仅一侧步骤允许稀疏(不强制连续)。

## Key Decisions

- **对齐键为步骤索引**:两分支从根统一递增编号,共享前缀天然同号;面板渲染也按 step_index。备选按因果边 ID/拓扑对齐——被否,跨分支 ID 不同,且复杂度过高。
- **状态按输出判定,明细双含输入输出**:同号同输出 → same;异输出 → diff;字段明细覆盖输入与输出两段(改输入、输出仍相同也可见)。备选仅按输出给集合——被否,满足不了"改了什么字段"。
- **字段 diff 用递归叶子路径 + 深度上限**:不展开超过固定深度的嵌套,超深退化为"值不同";数组按索引比对。避免大 prompt 递归爆炸。
- **diff 只读、无副作用**:不落库、不改数据;并发安全靠只读 + 既有串行落盘。
- **前端 divergentSteps 由 diff API 取代**:字段明细/状态在单一后端实现,前端只管渲染;原 set 推导删除,避免双份逻辑漂移。

## Risks / Trade-offs

- [大链路 diff 计算成本] → 对齐 O(n);字段 diff 深度受限;面板仅在 compare 选中时请求,不常驻轮询。
- [实时追加中 diff 漂移] → compare 分支实时追加时随 ownPoints 变化重新请求(与 useChain 同源触发),保证并排视图一致。
- [路径字符串可读性] → 采用 `messages[1].content` 式路径;UI 展示为可读分段,不追求 JSON Pointer 标准(非必要)。
- [仅一侧步骤的对齐语义] → 明确为"该步骤只存在于 A(或 B)";不猜测是否本可对齐。

## Migration Plan

无破坏性迁移;新增只读接口与前端改动,无 schema 变更,旧数据可直接 diff。
