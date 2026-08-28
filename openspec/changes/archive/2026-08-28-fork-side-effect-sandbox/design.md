# fork-side-effect-sandbox Design

## 概述

在既有「Fork = 前缀确定性回放 + 注入修改 + 后缀真调」上,给**后缀真调**加一道按 kind 的副作用闸门:真调之前查询 `sandbox` 策略,命中 `dry-run` / `block` 则改道"不真调 + meta 打标",未命中则维持真调。核心执行路径不动,默认行为零变化。

## 1. 策略模型(fork.py)

`ForkController.request_fork` 新增参数 `sandbox: Optional[dict] = None`,语义为 `{kind: policy}`:

```
kind   ∈ {llm, tool}                       # 对应 _models.KIND_LLM / KIND_TOOL
policy ∈ {allow, dry-run, block}           # allow=真调 / dry-run=模拟 / block=阻止
```

- 未配置的 kind → 视为 `allow`(向后兼容,现状不变)。
- 校验:任何 key 不在 kind 集合、或 value 不在 policy 集合 → `raise ForkError(可观测原因)`,不创建分支。
- `ForkPlan` 增加 `sandbox` 字段,随计划交付给执行侧。

```python
SANDBOX_POLICIES = ("allow", "dry-run", "block")
SANDBOX_KINDS = (KIND_LLM, KIND_TOOL)   # "llm", "tool"

@dataclass
class ForkPlan:
    ...
    sandbox: Optional[dict] = None

def request_fork(self, *, trace_id, from_branch, from_step,
                 modifications=None, dry_run=False, note=None, sandbox=None):
    # 现有空链 / 越界 / 归属校验之后、create_branch 之前:
    for kind, policy in (sandbox or {}).items():
        if kind not in SANDBOX_KINDS:
            raise ForkError(f"invalid sandbox kind: {kind}")
        if policy not in SANDBOX_POLICIES:
            raise ForkError(f"invalid sandbox policy {policy!r} for {kind}")
    ...
    plan = ForkPlan(..., sandbox=sandbox)
```

## 2. 执行游标透传(_context.py)

`ExecutionCursor` 增加 `sandbox: Optional[dict] = None` 槽与构造参数;`interceptor.acquire_context()` 消费 pending fork 时透传 `sandbox=plan.sandbox`。

## 3. 拦截器闸门(interceptor/base.py)

`_decide` / `_adecide` 的 fork 分支,在全局 `cursor.dry_run` 检查之后、`return call(), True` 之前:

```python
policy = self._sandbox_policy(cursor, dp)
if policy is not None:
    dp.meta["sandbox"] = policy          # "dry-run" | "blocked"
    return reconstruct(None), True       # 不真调;输出为空,与 dry_run 档同构
return call(), True
```

辅助:

```python
@staticmethod
def _sandbox_policy(cursor, dp) -> Optional[str]:
    sb = cursor.sandbox
    if not sb:
        return None
    p = sb.get(dp.kind)
    return p if p in ("dry-run", "block") else None
```

分层语义:
- `cursor.dry_run`(整链只读)先于沙箱生效——只读预览时沙箱无需参与。
- 沙箱只作用于"将要真调"的步骤,即 fork 后缀且未被 `output` 注入覆盖的决策点。
- `meta.sandbox` 落盘到该决策点,UI 与查询均可读到「这一步被沙箱拦了」。

## 4. API(/api/forks)

`POST /api/forks` 读取可选 `body["sandbox"]`,透传给 `request_fork`;`ForkError` 已由路由捕获返回 422,无需改错误处理。

## 5. UI

- **ForkPanel(App.jsx)**:新增「工具调用副作用策略」单选(放行 `allow` / 模拟执行 `dry-run` / 阻止 `block`),默认放行;`createFork` payload 携带 `sandbox: {"tool": policy}`(仅当非默认时传)。AdoptModal 确认保持现状(不带 sandbox)。
- **决策点详情**:`meta.sandbox` 存在时展示标记——`dry-run` →「模拟执行(沙箱)」、`blocked` →「被沙箱阻止」,用现有警示块风格。

## 数据流

```
ForkPanel: 选择工具副作用策略(默认 allow)
  → POST /api/forks {trace_id, branch_id, from_step, modifications, sandbox: {tool: policy}}
    → request_fork:校验 sandbox → ForkPlan.sandbox
  → session.trace() → interceptor.acquire_context() → ExecutionCursor(sandbox=plan.sandbox)
  → sroute/aroute fork 后缀决策点:
      前缀回放 → 注入修改 → 全局 dry_run? → sandbox 闸门(dp.kind 命中 dry-run/block → 不真调 + meta.sandbox)
      → 否则真调
  → 决策点落盘(mata.sandbox)→ UI inspector 展示沙箱标记
```

## 文件改动

- `agent_inspect/fork.py`:`SANDBOX_*` 常量、`request_fork` 校验、`ForkPlan.sandbox`。
- `agent_inspect/_context.py`:`ExecutionCursor.sandbox` 槽与参数。
- `agent_inspect/interceptor/base.py`:`acquire_context` 透传 + `_sandbox_policy` 闸门(sync/async)。
- `agent_inspect/_server/app.py`:`/api/forks` 接受 `sandbox`。
- `web/src/App.jsx`:ForkPanel 策略选择 + 决策点沙箱标记展示。
- `web/src/styles.css`:策略选择与沙箱标记样式(复用现有警示/标签风格)。
- `tests/unit/test_fork.py`:沙箱单测(dry-run / block / allow / 非法校验)。
- `tests/integration/test_server_e2e.py`:带沙箱 fork 端到端。
