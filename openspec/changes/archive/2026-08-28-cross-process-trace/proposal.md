# cross-process-trace

## Why

当前每条 trace 都是进程内独立的"一次运行"——`agent_inspect.start()` 只拦截本进程的 LLM/工具调用,记录进本进程的 SQLite。真实 Agent 系统往往**一个 Agent 派生子进程、子进程再跑另一段 Agent**(编排器 → 子任务执行器、主 Agent → 工具内嵌 Agent)。这些跨进程的子运行目前在面板上是**孤立的碎片**:看不到"这条 trace 是谁派生的、父进程的上下文是什么",无法还原一次端到端的多 Agent 任务。

现状:
- `Trace` 模型无父子关系,只有平铺的 `started_at` / `agent_name` / `lifecycle`。
- 子进程若要记录,只能各自 `start()` 到自己的 DB,面板完全无法关联。
- README 已把 **multi-Agent cross-process tracing** 列为 Phase 2,本 change 落地最小可用的跨进程关联。

本 change 引入**跨进程 trace 父子关联**:子进程通过环境变量声明"我属于父 trace X",其新 trace 落库时带上 `parent_trace_id`;API 与面板据此把子 trace 关联回父 trace,呈现一棵跨进程的因果树。

## What Changes

- **后端(数据模型 + 迁移)**:`Trace` 增加可空 `parent_trace_id`;`traces` 表新增该列(对既有库安全迁移,老行默认为空);`create_trace_with_root` / `create_trace` 接受可选父 id。
- **后端(跨进程继承)**:`Session` 构造时读取 `AGENT_INSPECT_PARENT_TRACE` 环境变量;随后新建的记录 trace(非 fork)自动以该值为父 trace id——子进程只要带着环境变量 `start()`,即自动挂到父 trace 下。fork 分支不受影响(仍属其所在 trace)。
- **API**:`Trace.to_dict` 携带 `parent_trace_id`;`GET /api/traces/{id}` 返回 `children`(直接子 trace 列表),供面板分组与溯源。
- **UI**:
  - trace 列表:子 trace 在父 trace 下缩进展示,带「跨进程」标签;点击子 trace 正常加载其链路。
  - trace 详情:展示父 trace 引用(存在时)与子 trace 数,提示"由另一进程派生"。
- **示例**:`examples/react_agent_cross_process.py` —— 父进程记录一段运行,`subprocess` 派生子进程(注入 `AGENT_INSPECT_PARENT_TRACE`),子进程同 DB 记录另一段,面板可见父子关联。
- **测试**:
  - 单元:带父 id 创建 trace;`to_dict` 携带 `parent_trace_id`;既有库迁移后老行父 id 为空;子 trace 可被父 id 查出。
  - e2e:子进程带 `AGENT_INSPECT_PARENT_TRACE` 记录 → 落库子 trace 的 `parent_trace_id` 正确;`GET /api/traces/{parent}` 的 `children` 含该子 trace。

## Out of scope

- 跨进程的实时事件流(SSE)汇聚——子进程独立记录,面板在父进程侧轮询/刷新看到新子 trace。
- 跨主机 / 远程 store 聚合——仅限共享同一 SQLite 文件的进程间关联。
- 子进程决策点内联到父链路渲染——只做 trace 级关联,决策点级内联留给未来 change。
- 传播链深度限制 / 环检测——父子为单向引用,面板按层级分组,不做图遍历算法。

## Criteria

- 子进程携带 `AGENT_INSPECT_PARENT_TRACE=<parent_id>` 记录的新 trace,其 `parent_trace_id == parent_id`。
- `GET /api/traces/{parent_id}` 返回的 `children` 包含该子 trace;子 trace 详情携带父 id。
- 既有数据库打开后不丢数据,老 trace 的 `parent_trace_id` 为空(向后兼容)。
- 面板 trace 列表对子 trace 缩进 + 标记「跨进程」,点击可加载其链路。
