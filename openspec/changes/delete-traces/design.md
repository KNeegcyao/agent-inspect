# delete-traces Design

## 概述

补齐 trace 生命周期管理的删除一环:store 级联删除 + `DELETE` 端点 + 面板删除入口(确认框)。删除是物理删除(本地单文件,无回收站概念);blob 不清理(内容寻址跨 trace 共享,孤儿块无行为影响,GC 推迟)。

## 1. Store(_server/store/queries.py)

```python
def delete_trace(self, trace_id: str) -> bool:
    """级联删除:decision_points → context_diffs → branches → traces 行。返回是否存在。"""
    with self._lock:
        if self._conn.execute("SELECT 1 FROM traces WHERE id=?", (trace_id,)).fetchone() is None:
            return False
        self._conn.execute(
            "DELETE FROM decision_points WHERE trace_id=?", (trace_id,))
        self._conn.execute(
            "DELETE FROM context_diffs WHERE branch_id IN (SELECT id FROM branches WHERE trace_id=?)",
            (trace_id,))
        self._conn.execute("DELETE FROM branches WHERE trace_id=?", (trace_id,))
        self._conn.execute("DELETE FROM traces WHERE id=?", (trace_id,))
        self._conn.commit()
    return True
```

- breakpoints 表按 trace_id 隔离,一并删除(该 trace 的断点无存在意义);
- blobs 不动(内容寻址,可能被其它 trace 引用)。

## 2. API(_server/app.py)

`DELETE /api/traces/{trace_id}`:

- 存在 → 200 `{"ok": true, "trace_id": ...}`;不存在 → 404 `{"error": "trace not found"}`;
- 发布事件 `trace.deleted`(SSE 订阅者刷新列表)。

## 3. UI(web/)

- **api.js**:`deleteTrace(traceId)` → DELETE;
- **App.jsx**:trace 列表项右上角悬停显示「删除」小按钮(与既有徽标并列,不挤主点击区);点击 → `window.confirm("将删除该 trace 及其全部分支与决策点,且不可恢复。确定?")` → 确认才调 API → 刷新列表;若删除的是当前选中 trace → 清空选择(traceData 置空回到空态);
- **styles.css**:删除按钮为危险色小字号(复用 --danger 变量),默认低透明度、行悬停时高亮。

## 4. 测试

- 单测(store 级联):建 trace + fork 分支 + 决策点 + 上下文 diff + 断点 → delete_trace → 相关表全清;另一条 trace 完好;删除不存在返回 False。
- e2e:两条 trace → DELETE 第一条 → 列表只剩第二条、详情/points 404、第二条 points 完好;再 DELETE 同一 id → 404。

## 5. 事件与实时性

`trace.deleted` 事件由 EventHub 广播;面板当前以手动「刷新列表」为主,SSE 已订阅的 App.jsx 可在收到该事件时调 loadTraces()(与 decision_point 分支并列)。
