// Agent-Inspect Node SDK 快速上手:录制 → 面板 Fork → 反事实重跑(全程离线,无 API key)。
//
//   node examples/quickstart.mjs
//
// 流程:
// 1. 起一个本地 mock OpenAI 兼容端点(脚本化回复,替代真实 LLM);
// 2. `start()` 一行启用:内嵌面板 + 自动开浏览器;
// 3. 用 OpenAI 客户端跑两步 LLM 链(被自动插桩为决策点);
// 4. 经面板同款契约 POST /api/forks 发起 Fork:注入修改第一条消息;
// 5. 再次执行 → 前缀回放(不真调)+ 注入生效,新分支落库;
// 6. 面板里两条分支并排对照(保持进程存活,Ctrl+C 退出)。
import { createServer } from "node:http";
import OpenAI from "openai";
import { start } from "../dist/src/index.js";

// ---- 1) mock OpenAI 兼容端点:按脚本回复 ----
const replies = ["MOCK_A", "MOCK_B", "MOCK_C"];
let hits = 0;
const mock = createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    const idx = Math.min(hits, replies.length - 1);
    hits += 1;
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        id: "chatcmpl-demo",
        model: "gpt-demo",
        choices: [
          { index: 0, message: { role: "assistant", content: replies[idx] }, finish_reason: "stop" },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      }),
    );
  });
});
await new Promise((r) => mock.listen(0, "127.0.0.1", r));
const mockUrl = `http://127.0.0.1:${mock.address().port}/v1`;

// ---- 2) 一行启用 ----
const session = await start({ autostartBrowser: true });
console.log(`[demo] 面板地址: ${session.url}`);

// ---- 3) 跑两步 LLM 链(自动插桩;mock 端点替代真实 LLM) ----
const client = new OpenAI({ apiKey: "sk-demo", baseURL: mockUrl });
const input = { model: "gpt-demo", messages: [{ role: "user", content: "1 + 2 等于多少?" }] };

const tid = await session.trace(async () => {
  for (let i = 0; i < 2; i++) {
    const r = await client.chat.completions.create(input);
    console.log(`[demo] 原始运行 step${i}:`, r.choices[0].message.content);
  }
});

// ---- 4) 经面板同款契约发起 Fork:注入修改第一条消息 ----
const detail = await (await fetch(`${session.url}/api/traces/${tid}`)).json();
const root = detail.trace.root_branch_id;
const fk = await (
  await fetch(`${session.url}/api/forks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trace_id: tid,
      branch_id: root,
      from_step: 0,
      modifications: [
        { step: 0, field: "input_context.messages[0].content", value: "9 + 9 等于多少?" },
      ],
      note: "quickstart: 改写第一条消息",
    }),
  })
).json();
console.log(`[demo] 已创建 fork 分支 ${fk.branch.id}(起点 step0,注入消息修改)`);

// ---- 5) 再次执行:消费 Fork(前缀回放不真调,注入生效,后缀真调) ----
await session.trace(async () => {
  const r = await client.chat.completions.create(input);
  console.log(`[demo] fork 分支执行输出:`, r.choices[0].message.content);
});
console.log("[demo] 面板里:同一条 trace 下「记录」与「Fork」两分支,可并排对比");
console.log("[demo] 按 Ctrl+C 退出");

process.on("SIGINT", async () => {
  mock.close();
  await session.stop();
  process.exit(0);
});
