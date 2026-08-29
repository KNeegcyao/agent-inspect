// OpenAI 插桩测试:本地 mock OpenAI 兼容端点,离线验证 记录/回放/注入/stream 放行。
import { assert, describe, it } from "./helpers.js";
import { createServer } from "node:http";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import OpenAI from "openai";
import { Store } from "../src/store.js";
import { ForkController } from "../src/fork.js";
import { Interceptor } from "../src/interceptor.js";
import { installOpenAIInterceptor, type Patcher } from "../src/patchers/openai.js";

async function mockOpenAI(responses: Array<Record<string, unknown>>): Promise<{
  url: string;
  hits: () => number;
  close: () => void;
}> {
  let hits = 0;
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      hits += 1;
      const idx = Math.min(hits - 1, responses.length - 1);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(responses[idx]));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as { port: number }).port;
  return {
    url: `http://127.0.0.1:${port}/v1`,
    hits: () => hits,
    close: () => server.close(),
  };
}

function plainReply(content: string): Record<string, unknown> {
  return {
    id: "chatcmpl-test",
    model: "gpt-test",
    choices: [
      { index: 0, message: { role: "assistant", content }, finish_reason: "stop" },
    ],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  };
}

async function makeSetup() {
  const dir = mkdtempSync(join(tmpdir(), "ai-oai-"));
  const store = new Store(join(dir, "s.json"));
  const fork = new ForkController(store);
  const interceptor = new Interceptor(store, fork); // 拦截器只消费自己控制器的 pending 队列
  const patcher = await installOpenAIInterceptor(interceptor);
  assert.ok(patcher, "openai 插桩应可用(dev 依赖已安装)");
  return { store, fork, interceptor, patcher: patcher as Patcher };
}

describe("openai instrumentation", () => {
  it("records real calls as decision points (input/output contract shapes)", async () => {
    const { store, patcher } = await makeSetup();
    const mock = await mockOpenAI([plainReply("MOCK_REPLY")]);
    try {
      const client = new OpenAI({ apiKey: "test", baseURL: mock.url });
      const resp = await client.chat.completions.create({
        model: "gpt-test",
        messages: [{ role: "user", content: "hi" }],
        temperature: 0.3,
      });
      assert.equal((resp as any).choices[0].message.content, "MOCK_REPLY");
      assert.equal(mock.hits(), 1);

      const trace = store.listTraces()[0];
      const pts = store.getDecisionPoints(trace.id, trace.root_branch_id!);
      assert.equal(pts.length, 1);
      assert.equal(pts[0].kind, "llm");
      assert.deepEqual(pts[0].input_context["messages"], [{ role: "user", content: "hi" }]);
      assert.equal(pts[0].input_context["model"], "gpt-test");
      assert.deepEqual(pts[0].input_context["params"], { temperature: 0.3 });
      assert.equal((pts[0].output as Record<string, unknown>)["content"], "MOCK_REPLY");
    } finally {
      patcher.restore();
      mock.close();
      store.close();
    }
  });

  it("fork replay returns recorded response without hitting the endpoint", async () => {
    const { store, fork, interceptor, patcher } = await makeSetup();
    const mock = await mockOpenAI([plainReply("FIRST"), plainReply("SECOND")]);
    try {
      const client = new OpenAI({ apiKey: "test", baseURL: mock.url });
      const input = {
        model: "gpt-test",
        messages: [{ role: "user" as const, content: "hi" }],
      };
      // 注意:裸调用各自成 trace(JS ALS 语义);多步链需显式游标作用域(对应 session.trace)
      const { runWithCursor, Cursor } = await import("../src/context.js");
      const created = store.createTraceWithRoot("agent");
      await runWithCursor(
        new Cursor({ traceId: created.trace.id, branchId: created.branch.id }),
        async () => {
          await client.chat.completions.create(input);
          await client.chat.completions.create(input);
        },
      );
      assert.equal(mock.hits(), 2);
      await fork.requestFork({
        traceId: created.trace.id,
        fromBranch: created.branch.id,
        fromStep: 1,
        dryRun: false,
      });

      // 无游标执行 → 消费 fork;step0 命中前缀回放(不打 mock);step1 真调(打 mock)
      await runWithCursor(null, async () => {
        const resp0 = (await client.chat.completions.create(input)) as unknown as {
          choices: { message: { content: string } }[];
        };
        assert.equal(resp0.choices[0].message.content, "FIRST");
        const resp1 = (await client.chat.completions.create(input)) as unknown as {
          choices: { message: { content: string } }[];
        };
        assert.equal(resp1.choices[0].message.content, "SECOND");
      });
      assert.equal(mock.hits(), 3, "step0 回放不打 mock;step1 真调打一次");
    } finally {
      patcher.restore();
      mock.close();
      store.close();
    }
  });

  it("stream:true passes through untouched (no decision point recorded)", async () => {
    const { store, patcher } = await makeSetup();
    const mock = await mockOpenAI([plainReply("NO_STREAM")]);
    try {
      const client = new OpenAI({ apiKey: "test", baseURL: mock.url });
      try {
        await client.chat.completions.create({
          model: "gpt-test",
          messages: [{ role: "user", content: "hi" }],
          stream: true,
        } as any);
      } catch {
        /* mock 不产 SSE:解析失败可接受,关键是不得进拦截器 */
      }
      const trace = store.listTraces()[0];
      const pts = trace ? store.getDecisionPoints(trace.id, trace.root_branch_id!) : [];
      assert.equal(pts.length, 0, "stream 调用不记录决策点");
    } finally {
      patcher.restore();
      mock.close();
      store.close();
    }
  });

  it("tool_calls in response mapped to contract shape", async () => {
    const { store, patcher } = await makeSetup();
    const mock = await mockOpenAI([
      {
        id: "chatcmpl-tc",
        model: "gpt-test",
        choices: [
          {
            index: 0,
            finish_reason: "tool_calls",
            message: {
              role: "assistant",
              content: null,
              tool_calls: [
                {
                  id: "call_1",
                  type: "function",
                  function: { name: "add", arguments: '{"x":1,"y":2}' },
                },
              ],
            },
          },
        ],
      },
    ]);
    try {
      const client = new OpenAI({ apiKey: "test", baseURL: mock.url });
      await client.chat.completions.create({
        model: "gpt-test",
        messages: [{ role: "user", content: "1+2?" }],
      });
      const trace = store.listTraces()[0];
      const pts = store.getDecisionPoints(trace.id, trace.root_branch_id!);
      const tc = (pts[0].output as Record<string, unknown>)["tool_calls"] as unknown[];
      assert.deepEqual(tc, [{ name: "add", args: { x: 1, y: 2 }, id: "call_1" }]);
    } finally {
      patcher.restore();
      mock.close();
      store.close();
    }
  });
});
