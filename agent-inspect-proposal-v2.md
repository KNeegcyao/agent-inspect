# Agent-Inspect — Agent 交互式调试器(技术方案 v2)

> 对 v1 的修订要点:① 承认 LangFuse 等开源竞品已占据 *observability*;② 旗舰功能从"断点"改为 **暂停→step→反事实 fork**;③ MVP 砍到 Python SDK + 一行起本地面板 + 单 trace 视图;④ 站在 OpenInference 语义上扩,不重造。

---

## 一、定位:别再说"没有开源方案"

这一节是整个方案能不能立得住的前提,必须先讲清。

**生态现状(事实):**
- **LangFuse**(MIT,可私有化):LLM/Agent **observability** 的事实标准。tracing、eval、prompt mgmt、datasets、analytics,生产采用很广。
- **Phoenix**(Arize 开源,Apache-2.0):tracing + eval + 内置 UI。
- **OpenInference / OpenLLMetry**:基于 OTel 的开源 instrumentation **语义约定**。
- LangSmith(Arize/AgentOps):偏商业化,但同属"事后看"。

**所以"一个成熟开源方案都没有"是错的。** v1 这句话必须删掉——拿去 Show HN,第一句被问的就是这个。

**真正的岔口在哪:** 上面这些全都是 **observability**——只读、事后看、回答"发生了什么"。**业界缺的是 debugger**——活体控制、能步进、能改、能重建分支,回答"为什么这样干、我改哪才有效"。对标的不是 LangFuse,是传统软件里的 **Chrome DevTools + pdb**,LangFuse 之于 DevTools,大约等于 APM 监控之于 IDE 调试器。

**一句话定位:**
> Agent-Inspect 是 Agent 的交互式 step-debugger。它不是又一个 tracing 平台,而是让开发者在某个决策点暂停、检查完整上下文、改 prompt 或工具返回、然后看分支跑出什么。

---

## 二、差异化(三句话能讲清)

对比 LangFuse / Phoenix / LangSmith:
- 它们是 **read-only viewer**(事后看 trace);我是 **live debugger**(能暂停、步进、注入)。
- 它们的 trace 是 **一条线展示完**;我提供 **counterfactual fork**(在某点开分支,改输入看输出)。
- 它们要 **部署 server + 配后端**;我是 **一行 `agent_inspect.start()` 自动弹浏览器**,零运维。

对比 OpenTelemetry:
- OTel span 是父子**树**;Agent 是**分支/并行/重试/多 Agent 通信的森林**。我站在 OpenInference 语义上扩 Agent 因果边,不自造。

差异化窄、可证伪、可传播。**唯一能讲出故事的硬核点是 counterfactual。**

---

## 三、核心执行模型:三态统一(v1 的最大修复)

v1 把"时间旅行回放"和"运行时修改"揉成一个招牌功能,架构上矛盾。这里用 **一个执行模型统一它们**:

**核心抽象 —— 决策点(Decision Point):**
Agent 执行 = 一串决策点。每个决策点有:`{agent_id, step_index, input_context, output}`。
- `input_context`:这一次决策的**完整输入**(发给 LLM 的全部 messages / 传给工具的参数)。
- `output`:这一次决策的**输出**(LLM response / 工具返回值)。

调试器对决策点能做三件事,对应三种模式:

```
┌──────────────────────────────────────────────────────────────┐
│  Mode A — Replay   (只读回放,  知识:为什么当时这样跑)        │
│  Mode B — Fork     (反事实,  旗舰:改某点,看后续会怎样)      │
│  Mode C — Live     (活体调试, 像 pdb:边跑边暂停)             │
└──────────────────────────────────────────────────────────────┘
```

**Mode A · Replay(只读回放):**
解释历史 trace 用。从已记录的决策点逐个回放(mock 掉所有 LLM/工具 call,直接喂记录的 output)。**不发任何新 API 请求**,零成本零副作用,适合做历史 diff、教学、bug 复现观看。

**Mode B · Fork(反事实)= 旗舰:**
拿一个**已记录的执行前缀**,确定性回放到决策点 N(用记录的 output),**在 N 注入用户的修改**(改 prompt / 改某工具返回 / 改温度),然后 **N+1 起交给框架真实执行**(真的调 LLM、真的调工具),并把后续每一决策点继续记录 + 允许进一步修改。

→ 这正是 v1"回放(只读)"和"运行时(读写)"矛盾的统一:
- 前半段用 **recorded output**(确定性、省钱、可复现)
- 后半段用 **live execution**(真实、可改、产生新分支)

**Mode C · Live(活体步进):**
attach 到正在跑的进程,在决策点装**条件断点**(LLM 返回含某串、token 数超阈值、某工具被调用时),命中即暂停,开发者检查上下文、可改值、继续(continue / step over / step into 任一决策点)。

> **三种模式共享同一套决策点抽象与拦截器**,这是 v2 相比 v1 最值钱的设计:不是三个功能,是一个模型的三种姿态。

---

## 四、旗舰功能:Counterfactual Fork

把"断点"从旗位降为支撑能力,**counterfactual fork 当旗舰**。

开发者真痛:
- 「这个 Agent 死循环了——改 prompt 能解开吗?」→ fork,改 prompt,看分支是否收敛。
- 「它为什么调了这个不该调的工具?」→ fork 到那步,把工具返回改成期望值,看下游决策是否跟着变。
- 「这次幻觉,换温度会好吗?」→ fork,改温度,并排看两棵分支。

这能回答"我改哪才有效",是 observability 永远回答不了的问题。**传播力比"断点调试"强一个量级**,因为 demo 一眼能看懂:同一棵树,两条分支并排,用户改一个值,世界分叉。

---

## 五、MVP 范围(狠砍,v1 的范围贪心病)

| 模块 | v1 | v2 MVP | v2 砍掉的理由 / 推迟 |
|---|---|---|---|
| SDK 语言 | Python+TS+Go | **仅 Python** | Agent 生态以 Python 为先,多语言是墓碑 |
| 框架插桩 | LangChain/CrewAI/AutoGen/OpenAI | **仅 LangChain + OpenAI SDK** | 两家覆盖绝大多数用户 |
| 存储 | SQLite+ClickHouse | **仅本地 SQLite** | 单机够用很久,ClickHouse 是运维负担 |
| 部署 | server+收集器 | **`agent_inspect.start()` 一行,自动弹浏览器** | 把 LangFuse"装 server"的摩擦打掉 |
| UI | 多面板仪表盘+DAG+评测 | **一页:单条 trace 的 思考→工具→结果 链路,能暂停、能看 prompt 全文** | 尖刀=零配置+一行+本地面板 |
| 旗舰 | 断点+时间旅行+运行时改 | **暂停→step→Counterfactual Fork** | 见上 |
| 调试接入 | Web+VSCode+JetBrains | **仅 Web(本地面板)** | IDE 插件等有用户再做 |
| 评测 | 内置 eval 引擎 | **移出 MVP,Phase 3 对接 Ragas/DeepEval** | 边界模糊,做早是包袱 |
| 可视化 | D3+WASM 自研引擎(>10万节点) | **D3+Canvas,够几千节点** | WASM/10万节点是过早优化 |

**MVP 钉死的卖点(给用户的一句话):
> "一行 `agent_inspect.start()`,Agent 跑起来自动弹一个本地 DevTools 面;你在任何一步能暂停、看全文 prompt、改一刀、重新跑分支。不要部署,不要后端,不要配置。"**

---

## 六、架构 & 数据流(MVP)

```
┌─────────────────────────────────────────────────────────┐
│  你的 Agent 脚本                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ agent_inspect.start()        ← 一行启用                │  │
│  │ (UI 自动开在 http://localhost:2999)               │  │
│  └───────────────────────────────────────────────────┘  │
└───────────────┬─────────────────────────────────────────┘
                │ shim 拦截
       ┌────────▼──────────────────────────────────────┐
       │  Interceptor (Python: 包 llm.invoke / 工具)   │
       │  - 登记决策点(input_context)                    │
       │  - Mode A: 返回 recorded output                     │
       │  - Mode B/Fork: 前缀用 recorded → N+1 真 call       │
       │  - Mode C: 命中断点则阻塞,等 UI 指令                  │
       └────────┬──────────────────────────────────────┘
                │ SSE/WebSocket(双向,实时)
       ┌────────▼──────────────────────────────────────┐
       │  Local Server (FastAPI)                       │
       │  - 长连接:推送决策点 / 接收修改 / 接收 continue     │
       │  - SQLite:存 trace + 决策点 + 分支图               │
       └────────┬──────────────────────────────────────┘
                │
       ┌────────▼──────────────────────────────────────┐
       │  本地 Web 面板 (React + D3)                     │
       │  - 单条 trace:决策链路树                         │
       │  - 任决策点:暂停 / 看 prompt 全文 / Fork 改值       │
       └───────────────────────────────────────────────┘
```

**关键点:Interceptor 是一切的地基。**
它把 `llm.invoke()` / `tool.call()` 包成"先登记、按模式决定要不要真调"的路由点。三种模式只是 Interceptor 在决策点的三种行为,无需三套代码。

**数据流(Fork 一次):**
1. 用户在面板点决策点 N 的 "Fork" → 改 prompt。
2. 面板经 WebSocket 下发 `{trace_id, branch_from: N, modification}`。
3. Server 让 Interceptor 切到 Fork 模式:**决策点 0..N 用 recorded output**(确定性),**N 处注入修改**,**N+1 起真调 LLM/工具**并继续记录新决策点。
4. 新分支实时回流面板,与原分支并排渲染。

---

## 七、项目结构(MVP,小)

```
agent-inspect/
├── sdk/                     # 仅 Python
│   ├── interceptor/         # 决策点拦截器(LangChain/OpenAI shim)
│   ├── recorder/            # 决策点记录 + 上下文快照
│   └── controller/          # 通信 tclient(连本地 server)
├── server/                  # 单个 FastAPI app
│   ├── store/               # SQLite schema + 查询
│   └── session/             # WebSocket 会话 + 分支管理
├── ui/                      # 单页 React 应用
│   └── TraceView/           # 决策链路树 + 决策点检查器
└── docs/                    
```

## 八、技术栈(克制)

- **Python SDK**:标准库 + `httpx/sseclient`,shim 用 monkeypatch/包装(同 LangChain instrumentation 路数)
- **Server**:FastAPI + SQLite(`aiosqlite`)+ WebSocket
- **UI**:React + Vite + D3 + Canvas(不上 WASM)
- **通信**:WebSocket(调试双向)+ SSE(事件流)
- **语义**:站 **OpenInference 语义约定**,在其上扩 Agent 因果边字段,不重造 OTel Agent 语义

---

## 九、关键技术难点 & 解法

**1. Agent 因果结构不是树 — 是森林 + 跨边。**
LLM Agent 会分支、并行、重试、多 Agent 通信。OTel 父子 span 损失信息。
→ 决策点之间存显式 **因果关系边**(`CAUSED_BY`),不止 parent-child。一条 trace 是个 DAG,并行/重试都是兄弟边。OpenInference 起步,加 `agent.step.cause` 语义字段。

**2. 上下文快照数据量爆炸(回放成本)。**
每个决策点的完整 prompt 可能巨大,复杂 Agent 海量决策点。
→ **增量快照**:决策点 `input_context` 只存与父决策点的 diff(共享前缀只存一次)。大工具输出存 hash + 去重存一次。
→ **两档**:Dev 模式全量快照(调试要完整上下文);Prod 模式只存摘要 + 大对象 hash(默认)。一条 config 决定。

**3. LLM 非确定性 vs 回放确定性。**
→ 本就不追求"重放出一模一样的对话"。纯回放用 recorded output(确定);Fork 则**故意**重新调 LLM(看改了之后会怎样),不追求确定。只有 Mode A réquiere 确定性,且它用记录值直接喂,天然确定。

**4. 并行/异步执行的状态传播。**
Python 用 `contextvars` 传当前 trace_id / branch_id / step_index,async 自动贯穿——这是 LangChain 等库已经验证过的机制。

**5. Fork 的"分叉点之后真实执行"如何安全。**
Fork 会真调 LLM/工具(花钱、有副作用)。→ UI 明确标注"此操作将真实执行 N+1 起";给一个 `dry_run`(N+1 也用 mock)的预览档。默认 fork **真执行**,但可一键切只读预览。

---

## 十、Roadmap(以 counterfactual 为主线)

**Phase 1 — MVP(2 个月):走通"一行起 + 看 + Fork"**
- Python SDK shims LangChain + OpenAI
- Interceptor:Mode A(回放)+ Mode B(Fork)双模
- 本地 SQLite + 自动弹浏览器
- 一页 UI:单 trace 链路,Fork 改 prompt 看分支
- 最小可用 demo(一个 LangChain agent 能被 fork)

**Phase 2(3-4 月):把 debugger 做厚**
- Mode C **Live**:attach 运行中进程 + 条件断点 + step/continue
- **并排分支 diff**(同一决策点的两棵子树对照)——这是传播爆点
- 工具返回值注入(不止改 prompt)
- 大上下文增量快照 + 高速渲染(几千节点)

**Phase 3(5-6 月):生态与生产**
- TS SDK(JavaScript Agent 生态起来后)
- OpenInference 兼容导入/导出(能吃别人产出的 trace 做 fork)
- 评测对接 Ragas/DeepEval(用 trace + fork 做回归集)
- 可选导出到任意 OTel 后端(产线存储,不绑 ClickHouse)

**Phase 4(长期)**
- VSCode/JetBrains 插件(条件:Phase3 DAU 起来才做)
- 回归脚下:trace → eval → counterfactual 修复 → 重跑的闭环
- 智能异常归因("这一步分叉到这里就坏了")
- 企业版 RBAC/SSO

---

## 十一、开源策略 & 成功指标(修虚荣指标)

- **Repo**:`github.com/agent-inspect/agent-inspect`
- **License**:Apache-2.0
- **放弃"第一周 500 star"**这个虚荣指标(刷得起来也沉得下去)。改为盯:
  - `pip` 周下载量
  - 是否被 LangChain / CrewAI 的官方 tutorial 主动引用
  - 仓库 issue 里出现"它帮我解开的 bug"案例数(质量指标)
- **传播打法**:
  - "用 counterfactual 解开一个 Agent 死循环"的短视频 demo(HN/Reddit/LocalLLaMA 通用款)
  - Show HN 标题别写 "no mature OSS exists",写**"LangFuse is observability; this is the Agent DevTools — pause, step, fork"**——精准对阵,反而显懂行

---

## 十二、v1 → v2 变更对照(给评审剧团)

| 项 | v1 | v2 | 为什么要改 |
|---|---|---|---|
| 竞品定位 | "无成熟开源" | 承认 LangFuse,自钉为 debugger | 旧表会被一句话戳穿 |
| 旗舰功能 | 时间旅行+断点 | Counterfactual Fork | 旧功能架构矛盾,且无传播故事 |
| 执行模型 | 模糊 | 三态统一(Replay/Fork/Live) | 修 v1 最大架构矛盾 |
| MVP 范围 | 多语言+多插件+评测+ClickHouse+WASM | Python+一行起+单 trace 一页 | 范围贪 = 项目死亡 |
| 语义 | 自造 OTel Agent 语义 | 站 OpenInference 扩 | 省一整轮标准化脏活 |
| 成功指标 | 500 star 第一周 | pip 下载+教程引用+案例数 | 虚荣指标会误导迭代 |

---

**下一步建议:** 先不改代码,先把 **Interceptor + 决策点 + Fork 三态** 的最小原型跑通(用 LangChain 的一个 ReAct agent 当 demo),把"一行 start → 自动弹面 → fork 改一刀看分支"这一条链跑顺。这一条链立住了,整个产品的故事就立住了。
