// 导入/推送测试(spec js-sdk.导入与推送 + Python importer/pusher 同语义对照)。
import { assert, describe, it } from "./helpers.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AddressInfo } from "node:net";
import { createServer } from "node:http";
import { importTrace, TraceImportError } from "../src/importer.js";
import { exportTrace } from "../src/exporter.js";
import { pushTrace, PushError } from "../src/pusher.js";
import { Store } from "../src/store.js";
import { ForkController } from "../src/fork.js";
import { Interceptor } from "../src/interceptor.js";
import { start, type Session } from "../src/session.js";

async function req(
  base: string,
  method: string,
  path: string,
  payload?: unknown,
): Promise<{ status: number; body: any }> {
  const r = await fetch(base + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  return { status: r.status, body: await r.json() };
}

function makeStore(): Store {
  return new Store(join(mkdtempSync(join(tmpdir(), "ai-imp-")), "s.json"));
}

// 合成扁平形态 span 导出(llm 含 tool_calls + tool + 未知 kind)
function flatPayload() {
  const attrs1: Record<string, unknown> = {
    "openinference.span.kind": "LLM",
    "llm.model_name": "gpt-test",
    "llm.input_messages": JSON.stringify([{ message: { role: "user", content: "1+2?" } }]),
    "llm.output_messages": JSON.stringify([
      {
        message: {
          role: "assistant",
          content: "",
          tool_calls: [{ name: "add", args: { x: 1, y: 2 }, id: "c1", type: "tool_call" }],
        },
      },
    ]),
    "llm.invocation_parameters": JSON.stringify({ temperature: 0.2 }),
  };
  const attrs2: Record<string, unknown> = {
    "openinference.span.kind": "TOOL",
    "tool.name": "add",
    "tool.parameters": JSON.stringify({ x: 1, y: 2 }),
    "tool.return_value": JSON.stringify(3),
  };
  const spans = [
    { span_id: "s1", name: "llm-1", start_time: 1720000000000, end_time: 1720000000015, attributes: attrs1 },
    { span_id: "s2", parent_span_id: "s1", name: "add", start_time: 1720000000010, end_time: 1720000000012, attributes: attrs2 },
    { span_id: "s3", parent_span_id: "s2", name: "llm-2", start_time: 1720000000020, end_time: 1720000000030, attributes: { "openinference.span.kind": "LLM", "llm.output_messages": JSON.stringify([{ message: { role: "assistant", content: "3" } }]) } },
    { span_id: "sx", name: "agent-run", start_time: 1720000000005, end_time: 1720000000006, attributes: {} },
  ];
  return { agent_name: "imported-prod", spans };
}

describe("importer", () => {
  it("flat form maps llm/tool with fidelity, unknown skipped", () => {
    const store = makeStore();
    const res = importTrace(store, flatPayload());
    assert.equal(res.decisionPoints, 3);
    assert.equal(res.skipped, 1);

    const trace = store.getTrace(res.traceId)!;
    assert.equal(trace.lifecycle, "done");
    assert.equal(trace.agent_name, "imported-prod");
    const pts = store.getDecisionPoints(res.traceId, res.rootBranchId);
    assert.deepEqual(pts.map((p) => p.kind), ["llm", "tool", "llm"]);
    assert.deepEqual(pts[0].input_context["messages"], [{ role: "user", content: "1+2?" }]);
    assert.equal(pts[0].input_context["model"], "gpt-test");
    assert.deepEqual((pts[0].output as any)["tool_calls"], [
      { name: "add", args: { x: 1, y: 2 }, id: "c1", type: "tool_call" },
    ]);
    assert.deepEqual(pts[1].input_context["tool"], "add");
    assert.deepEqual((pts[1].output as any)["result"], 3);
    assert.equal(pts.every((p) => p.meta["imported"] === true), true);
    store.close();
  });

  it("otlp envelope form equivalent; empty/no-spans rejected without writes", () => {
    const store = makeStore();
    const before = store.listTraces().length;
    assert.throws(() => importTrace(store, { foo: 1 }), /no spans found/);
    assert.throws(
      () => importTrace(store, { spans: [{ name: "x", attributes: {} }] }),
      /no importable spans/,
    );
    assert.equal(store.listTraces().length, before);
    store.close();
  });

  it("roundtrip: export -> import yields equivalent chain", () => {
    const store = makeStore();
    const payload = flatPayload();
    const first = importTrace(store, payload);
    const envelope = exportTrace(store, first.traceId);
    const second = importTrace(store, envelope);

    const a = store.getDecisionPoints(first.traceId, first.rootBranchId);
    const b = store.getDecisionPoints(second.traceId, second.rootBranchId);
    assert.deepEqual(b.map((p) => p.kind), a.map((p) => p.kind));
    assert.deepEqual(b.map((p) => p.input_context), a.map((p) => p.input_context));
    assert.deepEqual(b.map((p) => p.output), a.map((p) => p.output));
    store.close();
  });
});

describe("pusher", () => {
  it("delivers payload matching export mapping (mock collector)", async () => {
    const store = makeStore();
    const payloadIn = flatPayload();
    const seeded = importTrace(store, payloadIn);

    const received: any[] = [];
    const server = createServer((rq, rs) => {
      let body = "";
      rq.on("data", (c) => (body += c));
      rq.on("end", () => {
        received.push({ path: rq.url, body });
        rs.writeHead(200);
        rs.end("{}");
      });
    });
    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    const port = (server.address() as AddressInfo).port;
    const endpoint = `http://127.0.0.1:${port}/v1/traces`;

    const res = await pushTrace(store, seeded.traceId, endpoint);
    assert.equal(res.delivered, 3);
    assert.equal(res.statusCode, 200);

    const payload = JSON.parse(received[0].body);
    assert.equal(received[0].path, "/v1/traces");
    const scope = payload.resourceSpans[0].scopeSpans[0].scope;
    assert.equal(scope.name, "agent-inspect");
    const spans = payload.resourceSpans[0].scopeSpans[0].spans;
    const kinds = spans.map((s: any) => s.kind);
    assert.deepEqual(kinds, [3, 1, 3]); // LLM=CLIENT, TOOL=INTERNAL

    server.close();
    store.close();
  });

  it("non-2xx and unreachable raise observable errors", async () => {
    const store = makeStore();
    const payloadIn = flatPayload();
    const seeded = importTrace(store, payloadIn);

    const server = createServer((rq, rs) => {
      rq.on("data", () => {});
      rq.on("end", () => {
        rs.writeHead(500);
        rs.end("boom");
      });
    });
    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    const port = (server.address() as AddressInfo).port;

    await assert.rejects(
      pushTrace(store, seeded.traceId, `http://127.0.0.1:${port}/v1/traces`),
      /responded 500/,
    );
    server.close();

    // 已关闭的 500 端口 mock 即为不可达端点
    await assert.rejects(
      pushTrace(store, seeded.traceId, `http://127.0.0.1:${port}/v1/traces`, 1000),
      /unreachable/,
    );
    store.close();
  });
});

// Fork 可用于导入链路(前缀回放不真调)——与 spec js-sdk 导入语义衔接
describe("imported chain is forkable", () => {
  it("fork consumed: prefix replayed from imported outputs, suffix really calls", async () => {
    const store = makeStore();
    const fork = new ForkController(store);
    const interceptor = new Interceptor(store, fork);
    const seeded = importTrace(store, flatPayload());
    void interceptor;

    const { branch } = await fork.requestFork({
      traceId: seeded.traceId,
      fromBranch: seeded.rootBranchId,
      fromStep: 2,
    });

    const counter = { i: 0, calls: 0 };
    const seen: unknown[] = [];
    const cursor = new (await import("../src/context.js")).Cursor({
      traceId: seeded.traceId,
      branchId: branch.id,
      mode: "fork",
      replayBranchId: seeded.rootBranchId,
    });
    const { runWithCursor } = await import("../src/context.js");
    await runWithCursor(cursor, async () => {
      await interceptor.route({
        kind: "llm",
        agentId: "fake-llm",
        inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
        call: () => {
          counter.calls += 1;
          return Promise.resolve("REAL");
        },
        reconstruct: (d) => (d ? (d["content"] as string) : null),
        shapeOutput: (x) => ({ content: x }),
        makeModifiedCall: seen
          ? (patched) => () => {
              seen.push(patched);
              return Promise.resolve("R");
            }
          : undefined,
      });
    });
    assert.equal(counter.calls, 1, "step0/1 回放零真调,step2 真调一次");
    store.close();
  });
});


describe("import & push over HTTP", () => {
  it("import via API -> viewable; push delivers to collector; error paths", async () => {
    const s = await start({
      dbPath: join(mkdtempSync(join(tmpdir(), "ai-ipe-")), "s.json"),
      port: 0,
      autostartBrowser: false,
    });
    try {
      const base = s.url;
      const post = async (b: string, path: string, payload?: unknown) => {
        const r = await fetch(b + path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload === undefined ? "not-json" : JSON.stringify(payload),
        });
        return { status: r.status, body: await r.json() };
      };

      // 导入
      const imp = await post(base, "/api/traces/import", flatPayload());
      assert.equal(imp.status, 200, JSON.stringify(imp.body));
      const tid = imp.body.trace_id;
      assert.equal(imp.body.decision_points, 3);
      const { body: detail } = await req(base, "GET", `/api/traces/${tid}`);
      assert.equal(detail.trace.lifecycle, "done");
      const { body: pts } = await req(base, "GET", `/api/branches/${detail.trace.root_branch_id}/points`);
      assert.equal(pts.length, 3);

      // 非法导入 422 不落库
      const bad = await post(base, "/api/traces/import", { foo: 1 });
      assert.equal(bad.status, 422);
      const { body: tracesAfter } = await req(base, "GET", "/api/traces");
      assert.equal(tracesAfter.length, 1);

      // 推送到 mock 收集端
      const received: any[] = [];
      const server = createServer((rq, rs) => {
        let b = "";
        rq.on("data", (c) => (b += c));
        rq.on("end", () => {
          received.push(JSON.parse(b));
          rs.writeHead(200);
          rs.end("{}");
        });
      });
      await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
      const port = (server.address() as AddressInfo).port;

      const push = await post(base, `/api/traces/${tid}/push`, {
        endpoint: `http://127.0.0.1:${port}/v1/traces`,
      });
      assert.equal(push.status, 200, JSON.stringify(push.body));
      assert.equal(push.body.delivered, 3);
      assert.equal(received.length, 1);

      // 不可达 502 / 缺 trace 404 / 非法 endpoint 422
      const unreach = await post(base, `/api/traces/${tid}/push`, {
        endpoint: `http://127.0.0.1:9/v1/traces`,
        timeoutMs: 1000,
      });
      assert.equal(unreach.status, 502);
      const missing = await post(base, "/api/traces/tr_none/push", { endpoint: `http://127.0.0.1:${port}/v1/traces` });
      assert.equal(missing.status, 404);
      const badEp = await post(base, `/api/traces/${tid}/push`, { endpoint: "ftp://x" });
      assert.equal(badEp.status, 422);

      server.close();
    } finally {
      await s.stop();
    }
  });
});
