# add-js-sdk

## Why

Roadmap Phase 3 的收官项:**TS SDK**。当前调试器只覆盖 Python 生态(LangChain / OpenAI SDK),而 JS/TS 是 Agent 开发的另一半世界(Vercel AI SDK、LangChain.js、OpenAI Node SDK 之上的大量 Agent)。本 change 交付 JavaScript 运行时的等价调试能力,让"一行启用 + 面板 + Fork 反事实"的完整体验覆盖 Node 侧。

刻意收窄的 MVP 切片(与 Python 侧的对齐边界):

- **插桩面只做 OpenAI Node SDK**(`chat.completions.create`,与 Python 侧"conventional 入口"同哲学);LangChain.js 等推迟;
- **三种模式做足两种半**:record + fork(旗舰,前缀回放 + 注入 + 后缀真调 + dry_run 只读预览)+ 只读查看;Live(Mode C)推迟;
- **面板零改复用**:同一份 `web/dist`、同一 REST/SSE 契约的所需子集——这同时是对"契约是否真的与实现无关"的最强检验;
- **零第三方运行时依赖**:标准库 http + AsyncLocalStorage + 单文件 JSON 存储(存储引擎是实现细节,行为契约与 Python 侧一致)。

## What Changes

- **新子项目 `sdks/node/`**(TypeScript,ESM,Node >= 20,运行时零依赖,npm 包 `agent-inspect-node`):
  - `start()` 一行启用:内嵌 HTTP 服务(同契约子集)+ 面板托管 + 自动开浏览器;
  - 决策点拦截:LLM 调用 → 决策点(完整输入输出、顺序因果边),AsyncLocalStorage 贯穿 async(对应 Python 的 contextvars);
  - Fork 引擎:面板发起(起点/注入修改/只读预览/备注)→ 待执行队列 → 同进程下一次执行消费:前缀回放不真调、后缀真调、`output` 整段替换不真调、`input_context.路径` 修改真实调用;
  - 只读导出:`GET /api/traces/{id}/export`(与 Python 导出同契约);
  - 面板托管:直接服务 `web/dist` 构建产物。
- **契约子集**:`/api/traces`、`/api/traces/{id}`、`/api/branches`、`/api/branches/{id}/points`、`/api/branches/{a}/diff/{b}`(+adopt 预览)、`/api/forks`、`/api/traces/{id}/export`、`/api/traces/{id}/lifecycle`、`/api/events`(SSE);分支对比(含跨 trace)与采纳差异因此可用。
- **spec**:新增 `js-sdk` 能力(一行启用 / 自动拦截 / Fork / 面板契约一致)。
- **测试**:node:test 单测(存储/上下文/Fork 校验/拦截路由,mock fetch 离线确定性)+ HTTP 集成测试 + e2e(录制 → 面板 API 发起 Fork → 执行 → 对比);离线示例脚本。

## Out of scope

- 推送、导入端点(面板对应按钮会得到可观测的 404 错误提示);Live(Mode C);副作用沙箱策略;LangChain.js 插桩;流式(`stream: true`)调用插桩(原样放行);生产记录档(摘要 + 去重);多进程跨进程追踪。
- Python 侧任何改动(本 change 是纯增量新子项目)。

## Criteria

- JS 程序一行启用后,本机面板可访问,LLM 调用被记录为决策点(完整输入输出、因果链),面板链路/详情/Fork/对比可用;
- 不调用启用,JS 程序行为与无本系统时完全一致;
- 面板发起 Fork 后,同进程下一次执行进入分支:起点前回放(不真调)、注入修改生效、后缀真调落新分支;越界/空链拒绝且不落库;
- 全量测试(node:test)通过;Python 侧 pytest 零回归;`openspec validate --all` 通过;面板 `npm run build` 不回归。
