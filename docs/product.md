# Agent-Inspect — 产品定位书

> 面向"想搞清楚这到底是什么、为什么这么做、往哪走"的人。一句话门面见 [README](../README.md);技术细节与权衡见 [技术 proposal v2](../agent-inspect-proposal-v2.md);行为事实源见 [openspec/](../openspec/)。

---

## 1. 一句话

**Agent-Inspect 是 AI Agent 的交互式调试器**——把 Chrome DevTools / pdb 的体验搬进 Agent 开发:一行启用、本地面板自动开、能在任一决策点看完整 prompt、改一刀、分叉出一条分支看"改了之后会怎样"。

## 2. 痛点(开发者天天在问而工具答不上)

现有 Agent 工具几乎全是 **observability**(只读、事后看):LangFuse、Phoenix、OpenLLMetry 记录"发生了什么"。它们回答 **"Agent 做了什么?"**。

但开发者真正反复问的是反事实:

- 「Agent 死循环了——换个 prompt 能解吗?」
- 「它为什么调了这个工具?要是那工具返回的是 X,后面会不会就不一样?」
- 「这次在第七步幻觉——在那步降温度,能修吗?」

这是**调试**问题,不是观测问题。观测答不了"如果改了呢"——必须改、再跑。Agent 场景下没有这样的调试器,这就是 Agent-Inspect 要填的空缺。

## 3. 定位(不是又一个 tracing 平台)

| | LangFuse / Phoenix / OpenLLMetry | Agent-Inspect |
|---|---|---|
| 姿态 | 只读 viewer(事后看) | 活体 debugger(暂停、步进、改) |
| 回答 | "发生了什么" | "如果改了这一步会怎样" |
| 安装 | 自托管 server + 后端 DB | **一行**,本地面板自动开 |
| 探索成本 | 重新跑一遍并观测 | 从既有执行 fork,只重跑后缀 |
| 许可 | (各异,部分 MIT) | Apache-2.0 |

**它不是替代你的观测栈,是补它的另一侧。** 生产盯 LangFuse;**造 Agent、调 Agent** 时用 Agent-Inspect。

## 4. 核心思想

**① 决策是最小单元。** 每次 LLM 调用和每次工具调用都记成一个 *决策点*:完整 prompt 进、完整响应出,带 latency 与 token。

**② 三种模式,一个引擎。** *Replay*(只读回放)、*Fork*(旗舰)、(后续)*Live*(attach 运行中进程 + 条件断点)。三者是同一个拦截器的三种行为,不是三个拼起来的功能。

**③ Fork = 记录的前缀 + 真实的后缀。** 改动点之前用记录输出确定性回放(免费、不发 API),改动点之后真实重跑。这恰好统一了旧的"时间旅行(只读) vs 运行时改(读写)"的矛盾——它不是两个功能,是一个模型的后半段前半段用了不同的执行器。

**④ 站 OpenInference,不另起。** 在 OpenInference 语义约定上扩 Agent 因果边(`agent.step.cause`),不自造 OTel Agent 语义——让 trace 与你已有的观测世界互通,而不是又一孤岛。

## 5. 旗舰:Counterfactual Fork

把"断点"从旗位降为支撑能力,**反事实 fork 当旗舰**——因为只有它讲得出故事:

- 断点各家都在蹭,且只回答"停在这一步看啥"。
- 反事实 fork 回答"我改哪才有效",这是观测永远答不了的问题。
- 传播力强一个量级:demo 一眼能看懂——同一棵树,两条分支并排,用户改一个值,世界分叉。

**一次 fork 的手感:** 在决策点 N 点 Fork → 改 prompt / 工具返回 → 前缀 0..N 用记录输出免费回放 → N+1 起真实重跑 → 新决策点实时回流 → 与原分支并排对照。

## 6. 范围:MVP 有什么、显式没什么

**MVP 有:**
- 仅 Python SDK;自动插桩 **LangChain** 与 **OpenAI** SDK。
- Replay(只读)+ **Counterfactual Fork**(旗舰)。
- 一行起本地面板;本地文件存储;零外置后端。
- 单页 React UI:决策树、完整 prompt 检查、fork 交互、分支并排。

**显式不做(后续 change):**
- Live 活体模式(Mode C)。Phase 2。
- Fork 副作用沙箱。Phase 2(MVP 仅"真执行明示 + dry_run 只读预览")。
- TS/Go SDK;LangChain/OpenAI 以外的框架插桩。
- VSCode/JetBrains 插件;内置 eval;ClickHouse;WASM 大规模渲染;多 Agent 跨进程追踪。

**取舍:** 宁可一个调试器把一件事做到顶尖,不要一个平台把每件事做到勉强。

## 7. 为什么是现在(时机)

- Agent 可调性正停在"observability 满天飞、debugger 没人做"的阶段;生态空缺真实存在(LangFuse 是 observability,不是 debugger)。
- 分类比传统软件里 Datadog(APM) vs Chrome DevTools(IDE):观察 vs 调试,边界清晰、互不替代。
- 技术前提成熟:OpenInference 语义已有、Python Agent 生态收敛(LangChain/OpenAI 占大头),插桩与回放的实现路径被 LangChain instrumentation 验证过。
- 一行起的本地面板,部署摩擦被彻底打掉——开源冷启动的关键。

## 8. Roadmap

- **Phase 1 (MVP,2 个月)** — 一行起 + 看 + Fork:Python SDK(LangChain/OpenAI)+ Replay + Counterfactual Fork + 本地面板 + 单 trace 视图。
- **Phase 2 (3-4 月)** — debugger 做厚:Live(Mode C)+ 分支并排 diff + 工具返回注入 + Fork 副作用沙箱。
- **Phase 3 (5-6 月)** — 生态与生产:TS SDK;OpenInference 导入导出(吃别人的 trace 做 fork);评测对接 Ragas/DeepEval;可选导出到任意 OTel 后端。
- **Phase 4 (长期)** — IDE 插件(VSCode/JetBrains);trace→eval→fork 修复→重跑闭环;智能异常归因;企业版 RBAC/SSO。

## 9. 三层文档的分工

| 文档 | 给谁看 | 内容 |
|---|---|---|
| **README.md** | 访客 / 开发者 | 门面:一行起、差异、为什么 |
| **docs/product.md**(本文) | 想搞清定位的人 | 痛点 / 定位 / 三态 / 旗舰 / roadmap / 对比 |
| **agent-inspect-proposal-v2.md** | 要看技术权衡的人 | 市场框架 / 架构 / 关键决策 / 风险 |
| **openspec/** | 实现 / 验收 | 行为事实源(spec 是契约,prose 只解释 why) |

**铁律:行为以 `openspec/specs/` 为准。** prose 与 spec 冲突时,以 spec 为准;改行为 = 改 spec,不走 prose。

## 10. Open Questions

- **打包形态** — 是否 `pip install agent-inspect` 直装即用。**推荐**:可 pip 装包形态,MVP 先 `pip install -e .` 起源码,PyPI 打包留到发版前。apply 阶段定。
- **无头/CI 降级** — 已由 spec(`local-runtime 无头环境降级`)覆盖:检测到本机可用浏览器才自动开,否则仅打印本地 URL,无配置项。
- **Fork 副作用沙箱** — 已显式推至 Phase 2 独立 change;MVP 用真执行明示 + dry_run 处理可见性。

## 11. 立场

我们做的事很窄:让调 Agent 的人,有一个能改、能分叉、能看见"如果改了"的工具。不做 eval,不做 APM,不做企业平台——那些有别人在做。我们就做调试器这一件事。
