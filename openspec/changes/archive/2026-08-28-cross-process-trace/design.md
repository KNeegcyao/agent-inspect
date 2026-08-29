# cross-process-trace Design

## 概述

在既有"进程内单 trace 记录"上,加一条**跨进程父 trace 引用**:子进程通过 `AGENT_INSPECT_PARENT_TRACE` 环境变量声明父 trace,其新建记录 trace 落库时携带 `parent_trace_id`。核心记录路径不动(仍按"每次 `start()` 独立记录"),只是新建 trace 时多写一个可空外键;默认行为零变化(不设环境变量即与现状一致)。

## 1. 数据模型与迁移(_models.py / schema.py)

`Trace` 增加可空字段:

```python
@dataclass
class Trace:
    id: str
    started_at: float
    agent_name: str
    root_branch_id: Optional[str]
    lifecycle: str
    parent_trace_id: Optional[str] = None   # 跨进程父 trace(id),无则 None
```

`schema.py` 的 `traces` 建表语句追加 `parent_trace_id TEXT`;对既有库做**幂等迁移**(`connect()` 内检查 `PRAGMA table_info(traces)`,缺列则 `ALTER TABLE traces ADD COLUMN parent_trace_id TEXT`),老行默认为 `NULL`。

## 2. Store(_server/store/queries.py)

`create_trace_with_root(agent_name, parent_trace_id=None)` 与 `create_trace(agent_name, root_branch_id, parent_trace_id=None)` 写入新列;`get_trace` / `list_traces` 的 SELECT 与构造同步带上该列。

新增查询:

```python
def list_child_traces(self, parent_trace_id: str) -> list[m.Trace]:
    # SELECT ... FROM traces WHERE parent_trace_id=? ORDER BY started_at
```

## 3. 跨进程继承(session.py / recorder)

`Session.__init__` 读取 `os.environ.get("AGENT_INSPECT_PARENT_TRACE")`,写入 `self.recorder.parent_trace_id`;`Recorder.create_trace_and_root(agent_name)` 把该值透传给 `store.create_trace_with_root(..., parent_trace_id=self.parent_trace_id)`。

- 只在**新建记录 trace**(`interceptor.acquire_context` 无 pending fork 时)生效;
- fork 分支已归属其所在 trace,不受影响;
- 不设环境变量 → `parent_trace_id=None`,行为与现状完全一致。

## 4. API(_server/app.py)

- `Trace.to_dict()` 追加 `"parent_trace_id": self.parent_trace_id`。
- `GET /api/traces/{id}` 响应追加 `children`:

```python
return {
    "trace": t.to_dict(),
    "branches": [...],
    "children": [c.to_dict() for c in session.store.list_child_traces(trace_id)],
}
```

## 5. UI(App.jsx)

- **trace 列表**:`t.parent_trace_id` 存在时,该项缩进(左侧 padding)并加「跨进程」徽标;仍可点击加载。
- **trace 详情头**:在工具栏/标题区显示「父 trace · <short id>」(父存在)与「子 trace × N」(children.length > 0),点击父 id 切换到父 trace。
- **styles.css**:子 trace 缩进与「跨进程」徽标样式(复用现有 trace-item / 标签风格)。

## 6. 示例与测试

- `examples/react_agent_cross_process.py`:父进程 `start()`(临时 DB)→ `with session.trace()` 跑一段;`subprocess.run([python, child_script], env={**os.environ, "AGENT_INSPECT_PARENT_TRACE": tid, ...})`;子脚本 `start(db_path=同一文件, autostart_browser=False)` 记录另一段;结束打印父 trace 与子 trace id。
- 单测(test_recording 或新建 test_cross_process):
  - 带父 id 创建 → `parent_trace_id` 落库正确;`to_dict` 携带该字段;
  - 旧库(无列)打开迁移后老行父 id 为 `None`;
  - `list_child_traces(parent)` 返回直接子 trace。
- e2e(test_server_e2e):真实 `subprocess` 起子脚本(带 env),子 trace 落库后 `GET /api/traces/{parent}` 的 `children` 包含它。

## 数据流

```
父进程: session.trace() → trace P 记录决策点
  → 派生子进程 subprocess.run(child.py, env={AGENT_INSPECT_PARENT_TRACE: P})
子进程: Session(db_path=同文件) → recorder.parent_trace_id = P
  → acquire_context(无 pending fork) → create_trace_with_root(agent_name, parent_trace_id=P)
  → 子 trace C 落库(parent_trace_id=P)
面板: GET /api/traces → 每条带 parent_trace_id;子 trace 缩进 + 「跨进程」徽标
      GET /api/traces/P → children 含 C;详情头显示「父 trace · P」/「子 trace × 1」
```
