# Agent-Inspect MVP — 任务清单

> 顺序:拦截器 → 录制/存储 → Fork 引擎 → 本地运行时 → UI → 测试/验收 → 文档。每项勾选即完成。
> 对应 change:`add-agent-inspect-mvp`;能力 delta spec 见 `specs/<capability>/spec.md`。

## 1. Interceptor 决策点拦截器

- [ ] 1.1 定义决策点数据结构 + contextvars 上下文(trace_id/branch_id/mode/replay_cursor/branch_from_step)
- [ ] 1.2 LangChain `BaseChatModel`/`Runnable` 主入口包装为决策点(LLM kind)
- [ ] 1.3 LangChain `Tool`/`@tool` 包装为决策点(tool kind)
- [ ] 1.4 OpenAI 兼容 `chat.completions.create` 包装为决策点
- [ ] 1.5 模式路由:Replay 返回 recorded output;Fork `<=branch_from` 用 recorded、`>branch_from` 真调
- [ ] 1.6 启停非侵入:`start()` 启用、关闭后零开销原样运行
- [ ] 1.7 因果边登记(分支/并行/重试 cause)

## 2. Recorder 与 Store

- [ ] 2.1 决策点序列化 + meta(latency/tokens/error)
- [ ] 2.2 input_context 增量快照(diff against parent step,共享前缀只存一份)
- [ ] 2.3 output 大对象 content-addressed 去重(blob 表)
- [ ] 2.4 因果边 cause_edge 落库(DAG)
- [ ] 2.5 SQLite schema + 批量/WAL 写入
- [ ] 2.6 记录粒度两档(dev 全量 / prod 摘要+hash),config 切换

## 3. Fork 执行引擎

- [ ] 3.1 从决策点 N 发起新 branch(parent_branch_id + branch_from_step)
- [ ] 3.2 前缀确定性回放:0..N 用 recorded output,不发 API
- [ ] 3.3 注入修改:支持改 prompt / 工具返回值 / 参数
- [ ] 3.4 后缀 N+1 起真调 LLM/工具并记录到新 branch
- [ ] 3.5 分支图枚举(同 trace 多 branch)+ 前缀/后缀边界标记
- [ ] 3.6 真执行明示 + `dry_run` 只读预览档
- [ ] 3.7 分支隔离:不同 branch 决策点互不串(contextvars 分支)

## 4. 本地运行时与面板自启

- [ ] 4.1 一行 `agent_inspect.start()` 起 SDK + 内嵌服务
- [ ] 4.2 内嵌 FastAPI/uvicorn 单进程,择可用端口
- [ ] 4.3 自动开浏览器到本地面板;无头/CI 降级打印 URL
- [ ] 4.4 WebSocket 调试双向通道 + SSE 决策点事件流
- [ ] 4.5 零外置后端:SQLite 本地文件,无需 DB 部署
- [ ] 4.6 进程退出后历史留存(重启可读旧 trace)

## 5. 单条 Trace 决策视图(UI)

- [ ] 5.1 单页 React+Vite 脚手架,D3 布局 + Canvas 渲染节点
- [ ] 5.2 决策链路树渲染(思考→工具→结果),多分支分叉可视
- [ ] 5.3 决策点检查:展开完整 prompt/输入/输出
- [ ] 5.4 Fork 交互入口:对任决策点发起 fork + 注入修改
- [ ] 5.5 分支并排区分(原分支 vs fork 分支),可对照
- [ ] 5.6 实时追加执行中决策点(SSE 事件驱动);fork 后续实时回流

## 6. 测试与验收

- [ ] 6.1 拦截器/录制器/Fork 引擎单测(含 replay 确定性、fork 后缀真调、分支隔离)
- [ ] 6.2 e2e demo:一行起一个 LangChain ReAct agent → 自动开面 → fork 改 prompt → 看到分支
- [ ] 6.3 关闭拦截跑既有 LangChain/OpenAI 用例零回归
- [ ] 6.4 5 项能力 delta spec 全部 Scenario 逐条自检通过
- [ ] 6.5 `openspec validate --all` 通过

## 7. 文档与发布

- [ ] 7.1 README:一行起 quickstart + 与 LangFuse 差异(observability vs debugger)
- [ ] 7.2 把 `agent-inspect-proposal-v2.md` 关键决策链入 docs(Why)
- [ ] 7.3 打包形态决定(见 proposal Q2),apply 阶段定
- [ ] 7.4 归档:apply+验证通过后 `openspec archive add-agent-inspect-mvp --yes`,delta 并入主规格
