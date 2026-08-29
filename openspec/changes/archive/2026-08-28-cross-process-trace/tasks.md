# cross-process-trace Tasks

## 1. 后端:数据模型与迁移

- [x] 1.1 `Trace` 增加 `parent_trace_id: Optional[str]`;`to_dict` 携带该字段
- [x] 1.2 `traces` 表新增列 + 幂等迁移(既有库 ALTER,老行默认为空)

## 2. 后端:Store 读写

- [x] 2.1 `create_trace_with_root` / `create_trace` 接受并写入 `parent_trace_id`
- [x] 2.2 `get_trace` / `list_traces` 读取该列;新增 `list_child_traces(parent_trace_id)`

## 3. 后端:跨进程继承

- [x] 3.1 `Session` 读取 `AGENT_INSPECT_PARENT_TRACE` 环境变量 → `Recorder.parent_trace_id`
- [x] 3.2 `Recorder.create_trace_and_root` 透传给 store(仅新建记录 trace 生效)

## 4. API

- [x] 4.1 `GET /api/traces/{id}` 响应追加 `children`(直接子 trace)

## 5. UI

- [x] 5.1 trace 列表:子 trace 缩进 + 「跨进程」徽标,仍可点击加载
- [x] 5.2 trace 详情头:显示父 trace 引用与子 trace 数
- [x] 5.3 styles.css:缩进与徽标样式

## 6. 示例与测试

- [x] 6.1 `examples/react_agent_cross_process.py` 父子进程示例
- [x] 6.2 单元:带父 id 创建 / to_dict 携带 / 旧库迁移 / list_child_traces
- [x] 6.3 e2e:子进程带 env 记录 → 父 trace 的 children 含子 trace
- [x] 6.4 全量 pytest 通过 + `openspec validate` 通过 + vite build 通过

## 7. 文档与发布

- [x] 7.1 README 补「跨进程追踪」说明,更新 Phase 2 规划
- [x] 7.2 `openspec archive cross-process-trace --yes`
- [x] 7.3 commit + push(`6add837`)
