# agent-inspect-node

Agent-Inspect 的 JavaScript 运行时 SDK:一行启用,把 Node 侧 LLM Agent 的调用录成可查看、可 **Fork 反事实重跑** 的决策链。与 Python 版同契约、同一份面板。

## 快速上手

```bash
npm install agent-inspect-node   # 发版后;当前从仓库:先 npm run build 再引用 dist
```

```js
import { start } from "agent-inspect-node";

const session = await start();          // 内嵌面板 + 自动开浏览器(零运行时依赖)
// …你现有的 OpenAI 调用代码,无需改动——自动插桩…
const tid = await session.trace(async () => {
  await client.chat.completions.create({ model, messages });   // → 决策点
});
```

面板里:点链上任意决策点看完整 prompt / 输出 / 耗时;选主/对比分支并排对比;**发起 Fork**——前缀用记录输出免费回放,注入修改后真实重跑后缀。

## 语义要点(JS 与 Python 的差异)

- **多步链要显式括进 trace**:未包裹在 `session.trace()` 里的裸调用各自成一条 trace(JS 的 AsyncLocalStorage 不像 Python contextvar 那样向上传播);
- 自动插桩面:OpenAI Node SDK 的 `chat.completions.create`(`stream: true` 原样放行);未安装 openai 时静默跳过;
- 存储:单文件 JSON(默认 `~/.agent-inspect/agent-inspect-node.json`),与 Python 的 SQLite 不同库但行为契约一致;
- 面板契约子集:traces / branches / points / diff / adopt / forks / export / lifecycle / SSE / **Live 调试全端点**(附加/断点/暂停/单步/改输入/继续,含 at_step 幂等绑定)。**导入、推送、副作用沙箱暂不可用**(对应按钮会报错)。

## 开发

```bash
npm install && npm test    # tsc 构建 + node --test(全部离线,mock 端点)
node examples/quickstart.mjs   # 离线演示:录制 → 面板 Fork → 反事实重跑
```
