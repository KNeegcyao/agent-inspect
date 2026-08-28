# adopt-diff-to-fork Design

## 概述

在既有能力之上加一个「采纳」层:diff 引擎(`diff.py`)已产出字段级差异,`fork.py` 已具备注入修改 + 后缀真调。本 change 只加一条**从 diff 差异到 Modification 的映射**与对应的 API/UI 入口,不动两个引擎的核心语义。

## 数据流

```
BranchDiffView(UI)
  → POST /api/branches/{a}/diff/{b}/adopt  {from_step, steps: [...]}   (preview)
  → adopt_diff(...) 后端助手:
      1. diff_branches(...) 得 steps(与现有 diff 视图一致)
      2. 对用户选中的步骤,取 fields 中的差异 → 映射 Modification
      3. dry_run:request_fork(..., dry_run=True) 校验起点/空链,不落库
  → 返回 {modifications: [...], plan: {...}}  ← 只读,无副作用
UI 展示修改清单 → 用户确认
  → POST /api/forks (既有)  {trace_id, branch_id, from_step, modifications, note}
  → 创建新分支,入待执行队列 → 与普通 Fork 一致
```

## 差异 → 修改 映射规则(adopt.py 新增纯函数)

输入:diff 某步骤的 `fields: [{path, status, left, right}]`。

| diff 状态 | 映射为 |
|---|---|
| `path` 以 `input_context.` 开头(changed/added) | `Modification(step, field=path, value=right)` —— 改输入后真调 |
| `path == "output"`(changed) | `Modification(step, field="output", value=right)` —— 注入输出不真调 |
| `path == "output.content"` 等 output 子路径 | 整段 `output` 覆盖:`field="output", value=右侧完整 output`(与现有修改语义一致,避免子路径拼接歧义) |
| `status == "removed"`(仅左侧有) | 跳过 —— 无右侧值可采纳(本 change out of scope) |
| 同步骤无 fields / status=same | 不生成 |

- 输出区至多一条:`output`(整段覆盖);输入区按**叶子差异路径逐条**独立成条(如 `input_context.messages[0].content`),同一步骤可有多条输入修改。
- 输出整段覆盖的 `value` 取右侧分支该步骤的**完整 output**(实现上由 `preview_adopt` 单独构建右侧链路 `right_by_step` 索引,再传入 `adopt_modifications(steps, right_by_step)`)。
- 校验沿用 `fork.request_fork`:空链、起点越界,失败返回 422 + 原因。

## 采纳入口的语义(UI)

- BranchDiffView 头部加「采纳全部差异到 Fork」;每个 `diff` 步骤行内加「采纳」小按钮,只带该步骤的修改。
- 点击 → 请求 preview → 弹层列出 `{step, field, value}` 清单(字段可选勾选)+ 起点(from_step 默认该步骤,可改)+ 备注 → 确认 → 调既有 createFork。
- 采纳后刷新 trace,新分支出现在列表,与普通 Fork 分支同等待执行。

## 后端 API

新增(挂在既有 app.py 内):

```
POST /api/branches/{branch_a}/diff/{branch_b}/adopt
  body: { "from_step": int, "steps": [int], "note": str? }
  → 200 { modifications: [{step, field, value}], plan: {...}, dry_run: true }
  → 404 分支缺失 / 422 空链或起点越界
```

只读:调用 `request_fork(dry_run=True)` 校验但不落库(verify fork.py 的 dry_run 路径已满足"不创建分支")。确认后由 UI 走既有 `POST /api/forks`。

## 文件改动

- `agent_inspect/adopt.py`(新):`adopt_modifications(steps, right_by_step) -> list[Modification]` 纯映射 + `preview_adopt(...)` 只读预览。
- `agent_inspect/_server/app.py`:新增 adopt 路由(校验 + preview)。
- `web/src/api.js`:`adoptDiff(a, b, payload)`。
- `web/src/components/BranchDiffView.jsx`:采纳按钮 + 修改清单弹层(复用 DiffPanel 风格)。
- `web/src/App.jsx`:接入采纳 → createFork 流程。
- `web/src/styles.css`:采纳按钮/清单样式。
- `tests/unit/test_adopt.py`(新):映射规则单测。
- `tests/integration/test_server_e2e.py`:adopt API 端到端(preview 只读 + 确认创建)。
- `examples/react_agent_compare_traces.py`:采纳演示段(可选)。