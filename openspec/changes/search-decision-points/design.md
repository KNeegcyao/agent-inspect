# search-decision-points Design

## 概述

`agent_inspect/search.py` 提供只读检索:遍历 trace 全部分支,经既有解析层(read_branch_points,含 diff/blob 还原)取完整输入输出,序列化后做大小写不敏感子串匹配。纯计算,无写入,无索引(本地单文件规模线性扫描足够)。

## 1. 检索实现(`agent_inspect/search.py`)

```python
def search_trace(store, recorder, trace_id, query) -> list[dict]
```

- 分支集合:`store.list_branches(trace_id)`(含 fork 分支);
- 每分支 `recorder.read_branch_points(trace_id, branch_id)`(全量解析);
- 匹配:`json.dumps(text, ensure_ascii=False).lower()` 含 `query.lower()` 即命中;先查输入,再查输出(同点可两条命中,按 matched_in 区分);
- snippet:命中位置前后各 60 字符(越界截断),单行压缩(换行→空格);
- 结果:`{branch_id, step_index, kind, agent_id, matched_in, snippet}`,按 (branch 插入序, step_index, input 优先) 排序;
- 复杂度:O(点数 × 内容长度),本地规模(千点级)毫秒级。

## 2. API(`_server/app.py`)

`GET /api/traces/{trace_id}/search?q=<文本>`

- trace 缺失 → 404;`q` 缺失/为空 → 422 `{"error": "query parameter q is required"}`;
- 200:`{"trace_id", "query", "matches": [...]}`。

## 3. UI(`web/`)

- 工具栏(主分支选择旁)加搜索输入框(placeholder「搜索决策点内容…」),300ms 防抖调 API;空值清空结果;
- 结果浮层(trace-rel-bar 下方绝对定位列表):每条 = kind 徽标 + `#step` + 分支短 id + 「输入/输出」来源标签 + snippet(命中子串以 `<mark>` 高亮);
- 点击命中:`setActiveBranchId(match.branch_id)`(不同分支才切)+ `setSelectedId(match.dp_id)` → 右侧显示完整输入输出、链上高亮;浮层关闭;
- Esc / 清空 → 收起;样式复用现有 tooltip/浮层风格(绝对定位 + panel 底色 + border);
- api.js 增 `searchTrace(traceId, q)`。

## 4. 测试

- 单测(`tests/unit/test_search.py`):输入命中 / 输出命中 / 大小写不敏感 / 无命中空集 / 多分支结果排序 / snippet 截断与压行。
- e2e:录制两步链(内容含 "secret" 于 step1 输出)→ `GET /search?q=SECRET`(大写)命中 step1 标注 output → 404 / 422 路径。

## 数据流

```
GET /api/traces/{id}/search?q=xx
  → list_branches → read_branch_points(全量解析)
  → 序列化(lower)子串匹配 → snippet 合成 → 排序
面板: 工具栏搜索框 → 防抖 → 结果浮层 → 点击 → 切分支(如需)+ 选中决策点
```
