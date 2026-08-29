# add-js-sdk Design

## 概述

新子项目 `sdks/node/`(TypeScript,ESM,Node >= 20,运行时零依赖,npm 包名 `agent-inspect-node`)。与 Python 侧**同契约、同面板、同三态引擎哲学**,存储引擎换为单文件 JSON(实现细节,行为契约不变);async 贯穿用 AsyncLocalStorage 对应 contextvars。零改动复用 `web/dist` 面板——这是对"契约与实现解耦"的实测。

## 1. 目录与构建

```
sdks/node/
├── package.json          # name: agent-inspect-node, type: module, engines.node >= 20
├── tsconfig.json         # strict, NodeNext, outDir dist/
├── src/
│   ├── index.ts          # start() 导出
│   ├── session.ts        # Session:装配 store/recorder/interceptor/fork/server
│   ├── store.ts          # 单文件 JSON store(原子写:tmp+rename,写队列串行)
│   ├── context.ts        # AsyncLocalStorage 游标 + 模式常量
│   ├── models.ts         # Trace/Branch/DecisionPoint 类型 + newId(crypto.randomUUID 派生)
│   ├── fork.ts           # ForkController:发起校验 + 待执行队列 + 修改表
│   ├── interceptor.ts    # route():三态路由 + 登记落盘 + 注入路径补丁(_setPath/_splitKey 移植)
│   ├── patchers/openai.ts# 拦截 Chat.Completions.prototype.create(缺包静默跳过)
│   ├── server.ts         # node:http REST/SSE + 静态面板
│   ├── diff.ts           # 分支 diff(字段级 walk)+ adopt 预览映射
│   └── exporter.ts       # 信封导出(与 Python exporter 同契约)
├── tests/*.test.ts       # node:test
└── examples/quickstart.mjs
```

构建:`tsc` → `dist/`;npm 包 `files` 携带 `dist/` 与 `panel/`(构建时从 `web/dist` 拷贝)。开发依赖仅 typescript/@types/node/openai(测试用)。

## 2. 存储(store.ts)

单文件 JSON:`{traces: [], branches: [], points: []}`。写操作经 promise 队列串行,整文件原子重写(tmp + rename)——JS 单线程 + 本地单文件,满足"已完成登记即落盘、并发写不损坏"。查询子集:`createTraceWithRoot / listTraces / getTrace / setTraceLifecycle / createBranch / listBranches / getBranch / writeDecisionPoint / getDecisionPoints(branch) / countDecisionPoints(traceId) / lastStepBefore(branch, step)`。决策点全量内联存储(无增量快照/去重——dev 档语义,prod 档推迟)。

## 3. 上下文与三态路由(context.ts / interceptor.ts)

`AsyncLocalStorage<Cursor>`;`Cursor {traceId, branchId, mode, replayBranchId, branchFromStep, dryRun, stepIndex, lastDpId}`。`route({kind, agentId, inputContext, call, reconstruct, shapeOutput, makeModifiedCall})` 与 Python `sroute` 同构:

- 无游标 → `acquireContext()`:消费待执行 Fork,否则新建 record trace;
- replay/fork 前缀:读记录输出命中则回放(`needsRecord=false`);
- fork 后缀:`output` 修改 → 注入不真调;`input_context.*` 修改 → 补丁输入 + `makeModifiedCall`;`dryRun` → 空输出;否则真调;
- 收尾:shapeOutput / output_hash(sha256)/ latency / SSE 事件。

Fork 校验与 Python `request_fork` 对齐:空链 / 起点越界(0..last+1)/ 父分支归属 trace;非法不落库。

## 4. 插桩(patchers/openai.ts)

`start()` 时尝试 `import("openai")`:可用则包装 `Chat.Completions.prototype.create`——

- 输入形态:`{messages, model, params}`(create 参数去 messages/model 后为 params);
- 输出形态:`{content, tool_calls}`(取 `choices[0].message`,`tool_calls` 序列化为 `{name,args,id}`);
- reconstruct:返回最小响应形对象(`{id, model, choices: [{message: {role:'assistant', content, tool_calls}, index:0, finish_reason:'stop'}], usage}`),常见 Agent 循环零改动回放;
- `stream: true` 的调用原样放行(不拦截);未安装 openai → 静默跳过(零行为变化的一半)。

## 5. 服务与契约子集(server.ts)

`node:http`,Ephemeral 端口(8765 起扫描),端点:`GET /api/traces[lifecycle]`、`GET /api/traces/{id}`、`GET /api/branches`、`GET /api/branches/{id}/points`、`GET /api/branches/{a}/diff/{b}`、`POST /api/branches/{a}/diff/{b}/adopt`、`POST /api/forks`、`GET /api/traces/{id}/export`、`POST /api/traces/{id}/lifecycle`、`GET /api/events`(SSE:decision_point/trace.done)、静态面板(打包内 `panel/`,缺省回退占位页)。错误契约与 Python 一致(404/422 + `{"error"}`)。

diff/adopt 为纯计算移植(对齐步骤 same/diff/only_left/only_right + 字段级明细;采纳映射 output→整段、input 叶→路径)。import/push 端点不实现——面板按钮得到 404 JSON,错误条可见(MVP 例外,proposal 已声明)。

## 6. 测试(node:test)

- 单测:store 读写/串行;fork 校验(空链/越界/归属);拦截三态路由(真调/回放/注入/dryRun);注入路径补丁(嵌套/数组下标);导出信封形态。
- 集成:临时端口起服务 → REST 全链路(录制 → 分支枚举 → Fork 发起 → 消费执行 → diff);SSE 收到 decision_point 事件。
- 离线确定性:openai dev 依赖 + `new OpenAI({apiKey:'test', baseURL: mock})`,mock 用 `node:http` 起脚本化 chat.completions 假端点 → 插桩后的真实客户端调用被记录/回放,全程无真实网络。
- e2e:启用 → 跑两步链 → `POST /api/forks`(注入消息修改)→ 再跑 → 断言新分支 3 点、前缀回放、注入生效。

## 7. 示例

`examples/quickstart.mjs`:内置 mock 端点(脚本化回复)→ `start()` → 跑一段两步链 → 经 REST 发起 Fork(改消息)→ 再跑 → 打开面板可见记录/Fork 两分支。无需 API key。
