# global-search

## Why

单 trace 搜索(trace-search)解决的是"这条链里哪一步提到了 XX";但调试者同样常问**"上次哪个运行里出现过 XX?"**——报错信息、某个工具名、一段可疑的 prompt 片段,往往记不清在哪次运行。当前必须逐条 trace 点开搜索,trace 一多就退化成人工遍历。

本 change 把既有检索内核(`search_trace`)泛化为**跨 trace 全局搜索**:一个端点遍历全部 trace,命中按 trace 分组返回;面板在侧栏加一个全局搜索框,输入即出按 trace 分组的命中结果,点击命中直达该 trace 的具体决策点。

与单 trace 搜索的关系:同一检索内核、同一匹配语义(大小写不敏感子串、输入输出都参与);全局版是入口与分组粒度的扩展,不是新引擎。

范围克制:复用线性扫描(不建索引);每次 trace 最多返回前 N 条命中(防止超长链刷屏,合计数仍完整回报);不做正则/语义;不做生命周期过滤(全局检索的意义就在于翻旧账)。

## What Changes

- **后端**:`GET /api/search?q=<文本>` → 遍历全部 trace 调用既有 `search_trace`,按 trace 分组返回:`{"query", "total_matches", "results": [{trace_id, trace_name, lifecycle, started_at, match_count, matches(每 trace 最多前 50 条)}]}`;trace 按最近优先排列;无命中的 trace 不出现;`q` 缺失 422。
- **UI**:侧栏(筛选 chips 与列表之间)加全局搜索框——输入(300ms 防抖)后列表区切换为**按 trace 分组的命中视图**(trace 头:名称/时间/命中数;每 trace 最多展示 5 条命中片段,其余显示合计);点击 trace 头进入该 trace,点击命中**直达该 trace 的对应决策点**(自动切分支并选中);清空查询恢复常规列表。
- **spec**:`trace-search` 能力新增「跨 trace 全局搜索」requirement(3 场景)。
- **测试**:API e2e(多 trace 命中分组/合计数/422);UI 浏览器实测。

## Out of scope

- 搜索索引与增量检索;正则/语义;按生命周期或时间范围过滤的全局检索参数;命中片段的语义高亮以外的富展示。

## Criteria

- `GET /api/search?q=` 返回按 trace 分组的命中(每条含 trace 名称/时间/命中合计/片段),无命中的 trace 不出现,trace 按最近优先;
- 面板侧栏输入查询即出分组结果;点击命中后面板定位到该 trace 对应决策点(自动切分支并选中);点击 trace 头进入该 trace;清空查询恢复列表;
- 缺查询 422;全量测试通过,零回归。
