# global-search Design

## 概述

复用检索内核 `search_trace`:全局端点遍历 `store.list_traces()`(最近优先)逐条检索,命中按 trace 分组。面板侧栏加全局搜索框,输入后列表区整体切换为分组命中视图(清空即恢复)。无索引、线性扫描,与单 trace 搜索同语义。

## 1. API(`_server/app.py`)

`GET /api/search?q=<文本>`

- `q` 缺失/为空 → 422 `{"error": "query parameter q is required"}`;
- 实现:`for t in session.store.list_traces(): matches = search_trace(..., t.id, q)`;`matches` 非空的 trace 进入结果:
  `{trace_id, trace_name: t.agent_name || t.id, lifecycle, started_at, match_count: len(matches), matches: matches[:50]}`;
- 响应:`{"query", "total_matches": Σ, "results": [...]}`(200;全部无命中 → 空 results)。

每 trace 命中截前 50 条(`matches[:50]`),`match_count` 仍为全量——防止超长链刷屏且不丢信息。

## 2. UI(`web/`)

- 侧栏结构:筛选 chips 之后、trace 列表之前插入全局搜索输入(placeholder「全局搜索决策点内容…」);
- 状态:`globalQ`(输入)+ `globalResults`(防抖 300ms 调 API);`globalQ` 非空时列表区渲染分组视图,清空恢复常规列表;
- 分组视图:
  - trace 头按钮:`{trace_name} · {fmtTime} · {match_count} 命中` → `selectTrace(trace_id)` 并清空搜索(回到该 trace 的常规视图);
  - 命中按钮(每 trace 最多 5 条):复用 `.search-hit` 行(徽标 + 步骤 + 分支短 id + 来源 + Snippet 高亮)→ `jumpToGlobal(trace_id, m)`:`await selectTrace(trace_id)` 后 `setActiveBranchId(m.branch_id)` + `setSelectedId(m.dp_id)`;
  - 超过 5 条显示「…共 N 条命中(点击 trace 查看)」;
- api.js 增 `searchAll(q)`。

## 3. 样式

复用 `.search-hit` / `.search-snippet`;新增 `.global-search`(全宽输入)、`.gs-trace-head`(trace 头,风格同 trace-item)、`.gs-more`(合计提示,弱化色)。

## 4. 测试

- e2e:两条 trace(一条含 "needle" 两条命中、一条无命中)→ `GET /api/search?q=needle` 分组正确(无命中 trace 不出现、合计完整)、全部无命中空集、缺 q 422。
