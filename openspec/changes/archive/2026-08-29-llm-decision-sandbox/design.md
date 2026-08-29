# llm-decision-sandbox Design

## 概述

后端沙箱闸门已是按 `dp.kind` 泛化的单点(`_sandbox_policy` 命中 `dry-run`/`block` → 不真调 + `meta.sandbox`),`llm` 与 `tool` 同属合法 kind。因此本 change **不动核心执行路径**,只做三层补齐:UI 暴露 LLM 策略、沙箱标记按 kind 展示、测试与 spec 场景对齐。

## 1. UI:ForkPanel 双策略选择(App.jsx)

现状:`sandbox` 单一 state(默认 `allow`),只对 `tool` 生效,提交时 `payload.sandbox = {tool: sandbox}`(仅非默认时)。

改为两个 state,分别对应 LLM 决策点与工具决策点:

```jsx
const [sandboxLlm, setSandboxLlm] = useState('allow')   // LLM 决策点策略
const [sandboxTool, setSandboxTool] = useState('allow') // 工具调用副作用策略
```

`submit` 时组装 payload,只把非默认的 kind 写入 `sandbox`:

```jsx
const sb = {}
if (sandboxLlm !== 'allow') sb.llm = sandboxLlm
if (sandboxTool !== 'allow') sb.tool = sandboxTool
if (Object.keys(sb).length) payload.sandbox = sb
```

面板渲染两组并列单选,复用现有 `sandbox-field` / `radio-row` / `radio-opt` 样式:

- 「LLM 决策点策略」:放行(真调)/ 模拟执行(不真调,输出为空并标记模拟)/ 阻止(不真调并标记阻止)。
- 「工具调用副作用策略」:文案维持现状(放行 / 模拟执行 / 阻止)。

提交后两态均复位为 `allow`。

## 2. UI:沙箱标记按 kind 展示(App.jsx)

决策点详情已有 `point.kind`(inspector 顶部 `const kind = point.kind`)。沙箱标记处按 kind 给文案:

```jsx
{point.meta?.sandbox && (
  <div className={`sandbox-mark ${point.meta.sandbox}`}>
    {point.kind === 'llm'
      ? (point.meta.sandbox === 'dry-run' ? 'LLM 模拟(沙箱):未发起真实调用' : 'LLM 被沙箱阻止:未发起真实调用')
      : (point.meta.sandbox === 'dry-run' ? '模拟执行(沙箱):未发起真实调用' : '被沙箱阻止:未发起真实调用')}
  </div>
)}
```

样式无需新增(`sandbox-mark.dry-run` / `.blocked` 已存在)。

## 3. spec 场景(fork 能力)

在既有「Fork 副作用沙箱」requirement 内新增 LLM 场景,与工具场景对称:

- **LLM dry-run 模拟**:对 LLM 决策点配置 `dry-run` → 不真调,`meta.sandbox="dry-run"`,输出为空。
- **LLM block 阻止**:对 LLM 决策点配置 `block` → 不真调,`meta.sandbox="blocked"`。
- **混合配置**:`{llm: block, tool: allow}` → LLM 拦下、工具照常真调;未配置 kind 保持真调。

语义与工具完全同构:沙箱只作用于 fork 后缀"将要真调"的决策点,不真调时 `reconstruct(None)` 产出空输出(`_reconstruct_llm(None) → None`)。

## 4. 测试

**单元(unit/test_fork.py)**,沿用 `_fork_cursor(..., sandbox=...)` + `run_agent(..., kind=...)`:

- `test_fork_sandbox_llm_dry_run`: `sandbox={"llm": "dry-run"}`,跑 2 个 LLM 决策点 → `calls == 0`、`outs == [None, None]`、落盘 LLM 决策点 `meta.sandbox == "dry-run"`;再跑 1 个工具决策点(未配置 kind)→ 照常真调、无沙箱标记。
- `test_fork_sandbox_llm_block`: `sandbox={"llm": "block"}` → 不真调、`meta.sandbox == "blocked"`。
- `test_fork_sandbox_mixed`: `sandbox={"llm": "block", "tool": "allow"}` → LLM 拦下(`blocked`)、工具真调(`calls == 1`、无标记)。
- 既有工具沙箱 / 非法配置 / 默认真调测试不回归。

**e2e(integration/test_server_e2e.py)**,仿照 `test_fork_sandbox_e2e`:

- 携带 `sandbox: {"llm": "dry-run"}` 发起 Fork → 跑 LLM 步骤,`POST /api/forks` 后经 API 读决策点:LLM `meta.sandbox == "dry-run"`、工具照常真调。

## 数据流

```
ForkPanel: LLM 策略(默认 allow) + 工具策略(默认 allow)
  → POST /api/forks {..., sandbox: {llm: p, tool: q}}(省略 allow)
    → request_fork:校验 → ForkPlan.sandbox
  → acquire_context → ExecutionCursor(sandbox=plan.sandbox)
  → sroute/aroute fork 后缀决策点:
      前缀回放 → 注入 → 全局 dry_run? → _sandbox_policy(dp.kind 命中 dry-run/block → 不真调 + meta.sandbox)
      → 否则真调
  → 落盘(meta.sandbox)→ UI inspector 按 kind 展示沙箱标记
```

## 文件改动

- `openspec/changes/2026-08-29-llm-decision-sandbox/`:proposal / design / tasks / specs/fork/spec.md(delta)。
- `web/src/App.jsx`:ForkPanel 双策略单选 + 提交组装 `sandbox`;沙箱标记按 kind 文案。
- `tests/unit/test_fork.py`:LLM dry-run / block / 混合配置单测。
- `tests/integration/test_server_e2e.py`:LLM 沙箱 e2e。
- 后端(`fork.py` / `_context.py` / `interceptor/base.py` / `app.py`):**不改动**。
