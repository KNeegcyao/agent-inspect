// Live 调试 HTTP 集成测试:慢速 Agent + 面板同款契约全流程(spec js-sdk.JS 运行时 Live 调试)。
import { assert, describe, it } from "./helpers.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { start, type Session } from "../src/session.js";

async function withSession(fn: (s: Session, base: string) => Promise<void>): Promise<void> {
  const s = await start({
    dbPath: join(mkdtempSync(join(tmpdir(), "ai-live-")), "s.json"),
    port: 0,
    autostartBrowser: false,
  });
  try {
    await fn(s, s.url);
  } finally {
    await s.stop();
  }
}

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

async function waitPaused(base: string, tid: string, step: number, timeout = 5000): Promise<any> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const { body } = await req(base, "GET", `/api/debug/${tid}/state`);
    if (body.paused_at === step) return body;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error(`not paused at ${step}`);
}

describe("live debug over HTTP", () => {
  it("attach -> breakpoint -> pause -> step -> modify -> continue -> patched on disk", async () => {
    await withSession(async (session, base) => {
      const scripted = ["s0", "s1", "s2"];
      const counter = { i: 0, calls: 0 };

      // 慢速 Agent(后台):三步链,支撑面板异步操作
      const agentDone = session
        .trace(async () => {
          // 起步缓冲:给主线程 attach + 设断点留时间(等价 Python e2e 的 start.wait)
          await new Promise((r) => setTimeout(r, 300));
          for (let k = 0; k < 3; k++) {
            await session.interceptor.route({
              kind: "llm",
              agentId: "fake-llm",
              inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
              call: async () => {
                counter.calls += 1;
                const v = counter.i < scripted.length ? scripted[counter.i] : null;
                counter.i += 1;
                return v;
              },
              reconstruct: (d) => (d ? (d["content"] as string) : null),
              shapeOutput: (x) => ({ content: x }),
              makeModifiedCall: (patched) => async () => "EDITED_RUN",
            });
            await new Promise((r) => setTimeout(r, 20));
          }
        })
        .catch((e) => e);

      // 等待 agent trace 建立
      const tid = await new Promise<string>((resolve) => {
        const t0 = Date.now();
        const poll = () => {
          const ts = session.store.listTraces();
          if (ts.length) resolve(ts[0].id);
          else if (Date.now() - t0 > 3000) resolve("");
          else setTimeout(poll, 10);
        };
        poll();
      });
      assert.ok(tid, "agent trace should exist");

      // attach(running)→ 断点
      const at = await req(base, "POST", `/api/debug/${tid}/attach`, {});
      assert.equal(at.status, 200);
      assert.equal(at.body.attached, true);
      const bp = await req(base, "POST", `/api/debug/${tid}/breakpoints`, { kind: "llm" });
      assert.equal(bp.status, 200);

      await waitPaused(base, tid, 0);
      assert.equal(counter.calls, 0, "暂停点不真调");

      // 单步 → step1;重复投递 released=false 不跳暂停点
      const st1 = await req(base, "POST", `/api/debug/${tid}/step`, { at_step: 0 });
      assert.equal(st1.body.released, true);
      await waitPaused(base, tid, 1);
      const dup = await req(base, "POST", `/api/debug/${tid}/step`, { at_step: 0 });
      assert.equal(dup.body.released, false);
      await waitPaused(base, tid, 1); // 仍停在 1

      // 改输入并继续
      const md = await req(base, "POST", `/api/debug/${tid}/modify`, {
        step: 1,
        field: "input_context.messages[0].content",
        value: "EDITED",
      });
      assert.equal(md.status, 200);

      // 移除断点 + 继续(绑定当前暂停点)
      await req(base, "DELETE", `/api/debug/${tid}/breakpoints/${bp.body.id}`);
      const { body: stBody } = await req(base, "GET", `/api/debug/${tid}/state`);
      await req(base, "POST", `/api/debug/${tid}/continue`, { at_step: stBody.paused_at });
      await agentDone;
      // step0/step2 真调各计一次;step1 走 modify 的替换调用(不经 counter)
      assert.equal(counter.calls, 2);

      // 落盘:step1 输入已替换
      const { body: data } = await req(base, "GET", `/api/traces/${tid}`);
      const root = data.trace.root_branch_id;
      const { body: pts } = await req(base, "GET", `/api/branches/${root}/points`);
      assert.deepEqual(
        (pts[1].input_context["messages"] as unknown[])[0],
        { role: "user", content: "EDITED" },
      );
      assert.equal(pts[1].output["content"], "EDITED_RUN"); // 替换调用通道的产物
      const { body: after } = await req(base, "GET", `/api/traces/${tid}`);
      assert.equal(after.trace.lifecycle, "done");
    });
  });

  it("attach guards: missing trace 404 / not running 422", async () => {
    await withSession(async (session, base) => {
      const miss = await req(base, "POST", "/api/debug/tr_none/attach", {});
      assert.equal(miss.status, 404);
      // 造一条已完成的 trace
      await session.trace(async () => {
        await session.interceptor.route({
          kind: "llm",
          agentId: "fake-llm",
          inputContext: { messages: [], model: "fake", params: {} },
          call: () => Promise.resolve("x"),
          reconstruct: (d) => (d ? (d["content"] as string) : null),
          shapeOutput: (x) => ({ content: x }),
        });
      });
      const { body: traces } = await req(base, "GET", "/api/traces");
      const done = traces[0]; // 已完成的 trace
      const notRun = await req(base, "POST", `/api/debug/${done.id}/attach`, {});
      assert.equal(notRun.status, 422);
    });
  });
});
