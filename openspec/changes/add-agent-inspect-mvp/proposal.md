# Agent-Inspect MVP — 初始基线提案

## Why

Agent 可调性/可调试处于"observability 满天飞、debugger 没人做"的阶段。LangFuse(MIT)、Phoenix(Arize 开源)、OpenInference-Otel 已占据 **observability**(只读、事后看);业界缺的是 **interactive agent debugger**——能暂停、步进、改、重建分支,回答"为什么这样干、我改哪才有效"。对标不是 LangFuse,是传统软件的 Chrome DevTools + pdb。

v2 方案(见仓库根 `agent-inspect-proposal-v2.md`)据此收敛:MVP 只做 **Replay(只读回放)+ Counterfactual Fork(反事实调试)**,一行起的本地面板,把 LangFuse"装 server + 配后端"的部署摩擦打掉。本 change 提出 MVP 所需的 5 项能力基线。

## What Changes

- 新增 **决策点拦截与自动插桩**能力:把 LLM 调用与工具调用统一登记为决策点,按执行模式(Replay/Fork)路由是否真实调用。
- 新增 **决策点记录与存储**能力:记录决策点完整输入/输出/latency/token,大对象去重、上下文增量快照,本地文件持久化、进程重启后可被回放查询;提供 dev/prod 两档记录粒度。
- 新增 **Counterfactual Fork** 能力(旗舰):从任一决策点新建分支,前缀确定性回放(用 recorded output)→ 注入修改 → 后缀真实执行并继续记录;分支可枚举、并排比较;fork 真执行默认明示、可切只读预览;分支执行相互隔离。
- 新增 **本地运行时与面板自启**能力:一次调用即启用拦截与本地面板,自动开浏览器,本机内嵌服务、实时双向事件流、本地文件存储,无需部署独立 server 或外置后端。
- 新增 **单条 Trace 决策视图**能力:单页渲染决策链路树(思考→工具→结果),决策点可检查完整 prompt/输入/输出,可在面板发起 fork 与注入修改,实时追加执行中的决策点,分支可并排区分。

## Capabilities

- **New Capabilities**
  - `interception` — 决策点登记、主流框架自动插桩、执行模式按上下文路由、非侵入启停、执行上下文传播。
  - `recording` — 决策点完整记录、大对象去重、增量上下文快照、本地持久化与重启可查、可配记录粒度、因果关系可追溯。
  - `fork` — 从决策点发起分支、前缀确定性回放、注入修改、后缀真实执行、真执行明示与只读预览、分支图枚举与并排、分支执行隔离。
  - `local-runtime` — 一次调用启用、自动唤起本地面板、本机内嵌服务、端口冲突自适应、实时双向消息、零外置后端可用。
  - `trace-ui` — 单条 trace 决策链路视图、决策点细节检查、fork 交互入口、分支并排区分、执行中实时追加。

- **Modified Capabilities**
  - (none — greenfield,本 change 提出初始能力基线)

## Impact

- 代码:`sdk/`(Python:interceptor/recorder/controller)、`server/`(本机内嵌服务、store、session/分支管理)、`ui/`(单页 TraceView);尚无现存代码,纯新增。
- 测试:Python SDK 拦截器/录制器/Fork 执行模型的单测;一行起 e2e(启用 → 自动开面 → fork 一刀看分支);UI 关键交互快照;关闭拦截跑既存 LangChain/OpenAI 用例零回归。
- 依赖:Python(标准库 + httpx/sseclient)、本机服务(FastAPI + aiosqlite)、UI(React + Vite + D3 + Canvas);**不引入** ClickHouse / WASM / 任何 IDE 平台 SDK。
- 兼容:greenfield 无兼容性负担;MVP 内不破坏被插桩框架(LangChain/OpenAI)既有行为——关闭拦截即零开销原样运行。

## Out of Scope (Non-Goals of this change)

- Live 活体调试(Mode C:attach 运行中进程 + 条件断点 + step/continue)——Phase 2 另立 change。
- Fork 副作用沙箱快照(限制 fork 后缀对外部环境的写副作用)——Phase 2 另立独立 change;MVP 仅以真执行明示 + dry_run 处理可见性。
- TS/Go SDK;插桩 LangChain/OpenAI 以外的框架(CrewAI/AutoGen 等)。
- VSCode/JetBrains 插件;内置 eval 引擎;ClickHouse 或任意远端后端导出;>10万节点 WASM 渲染;多 Agent 跨进程协作追踪。

## Open Questions

- Q1(已收敛):Fork 后缀"真实执行"调用的是**实际环境**的工具(可能改外部状态);"fork 副作用沙箱快照"不在本 change 范围,**推进至 Phase 2 另立独立 change**(已同步写入 Out of Scope)。MVP 内仅以"真执行明示 + dry_run 只读预览"处理副作用可见性。
- Q2(待人工拍):本地零配置是否需支持 `pip install agent-inspect` 单条命令直装即用?**推荐答案**:采用单独可 pip 安装的 Python 包形态(MVP 先以源码 + `pip install -e .` 起,P0 打包 PyPI 留到发版前)。最终于 apply 阶段确认。
- Q3(已收敛):无头/CI 环境降级——spec 已由 `local-runtime 无头环境降级` scenario 覆盖("不报错,改为输出可访问地址")。**默认策略定为**:自动开浏览器仅在能检测到可用本机浏览器时触发,否则仅打印本地 URL;无额外配置项。
