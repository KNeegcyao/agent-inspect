// 拦截器 + 服务集成测试:REST 契约 / Fork 全链路 / diff / adopt / export / SSE / 错误路径。
import { assert, describe, it } from "./helpers.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { start, type Session } from "../src/session.js";

async function withSession(fn: (s: Session, base: string) => Promise<void>): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), "ai-sess-"));
  const s: Session = await start({ dbPath: join(dir, "s.json"), port: 0, autostartBrowser: false });
  const base = s.url;
  try {
    await fn(s, base);
  } finally {
    await s.stop();
  }
}

async function get(base: string, path: string): Promise<{ status: number; body: any }> {
  const r = await fetch(base + path);
  return { status: r.status, body: await r.json() };
}

async function post(base: string, path: string, payload: unknown): Promise<{ status: number; body: any }> {
  const r = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { status: r.status, body: await r.json() };
}

// 顺序执行 n 个 LLM 决策点(脚本化,确定性)
function makeRunner(session: Session, scripted: string[]) {
  const counter = { i: 0, calls: 0 };
  return {
    get calls() {
      return counter.calls;
    },
    async run(n: number): Promise<(string | null)[]> {
      const outs: (string | null)[] = [];
      for (let k = 0; k < n; k++) {
        outs.push(
          (await session.interceptor.route({
            kind: "llm",
            agentId: "fake-llm",
            inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
            call: () => {
              counter.calls += 1;
              const v = counter.i < scripted.length ? scripted[counter.i] : null;
              counter.i += 1;
              return Promise.resolve(v);
            },
            reconstruct: (d) => (d ? (d["content"] as string) : null),
            shapeOutput: (x) => ({ content: x }),
          })) as string | null,
        );
      }
      return outs;
    },
  };
}

describe("server contract", () => {
  it("record -> traces/branches/points -> fork -> consume -> diff -> adopt -> export", async () => {
    await withSession(async (session, base) => {
      const runner = makeRunner(session, ["a", "b", "c"]);
      await session.trace(() => runner.run(3));
      assert.equal(runner.calls, 3);

      // trace 列表与详情
      const list = await get(base, "/api/traces");
      assert.equal(list.status, 200);
      const tid = list.body[0].id;
      const detail = await get(base, `/api/traces/${tid}`);
      assert.equal(detail.status, 200);
      assert.equal(detail.body.trace.lifecycle, "done");
      const root = detail.body.branches[0].id;

      // 决策点
      const pts = await get(base, `/api/branches/${root}/points`);
      assert.equal(pts.body.length, 3);
      assert.equal(pts.body[0].output.content, "a");

      // 全局分支索引
      const allb = await get(base, "/api/branches");
      assert.ok(allb.body.some((b: any) => b.id === root && b.trace_name));

      // 非法 fork:越界 422 / 未知 trace 404
      const bad = await post(base, "/api/forks", { trace_id: tid, branch_id: root, from_step: 99 });
      assert.equal(bad.status, 422);
      const missing = await post(base, "/api/forks", {
        trace_id: "tr_none",
        branch_id: "br_none",
        from_step: 0,
      });
      assert.equal(missing.status, 404);

      // fork + 注入消息 → 消费执行 → 新分支(前缀回放 + 注入真调)
      const fk = await post(base, "/api/forks", {
        trace_id: tid,
        branch_id: root,
        from_step: 0,
        modifications: [{ step: 0, field: "input_context.messages[0].content", value: "EDITED" }],
        note: "e2e",
      });
      assert.equal(fk.status, 200, JSON.stringify(fk.body));
      const forkBranch = fk.body.branch.id;

      const runner2 = makeRunner(session, ["ignored"]);
      let seen: unknown = null;
      await session.trace(async () => {
        // 第一次 route 无游标 → acquireContext 消费 pending fork(注入生效)
        await session.interceptor.route({
          kind: "llm",
          agentId: "fake-llm",
          inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
          call: () => Promise.resolve("R1"),
          reconstruct: (d) => (d ? (d["content"] as string) : null),
          shapeOutput: (x) => ({ content: x }),
          makeModifiedCall: (patched) => () => {
            seen = patched;
            return Promise.resolve("R1");
          },
        });
        await runner2.run(1); // 第二次 route 在 fork 游标内
      });
      assert.deepEqual(
        (seen as Record<string, unknown>)["messages"],
        [{ role: "user", content: "EDITED" }],
      );
      const fpts = await get(base, `/api/branches/${forkBranch}/points`);
      assert.equal(fpts.body.length, 2);
      assert.deepEqual(fpts.body[0].input_context.messages, [{ role: "user", content: "EDITED" }]);

      // diff(跨分支)
      const diff = await get(base, `/api/branches/${root}/diff/${forkBranch}`);
      assert.equal(diff.status, 200);
      assert.ok(diff.body.summary.diff >= 1);
      assert.ok(diff.body.trace_a);

      // 采纳预览(只读)
      const adopt = await post(base, `/api/branches/${forkBranch}/diff/${root}/adopt`, { from_step: 0 });
      assert.equal(adopt.status, 200);
      assert.equal(adopt.body.dry_run, true);
      assert.ok(Array.isArray(adopt.body.modifications));

      // 导出(附件头 + 信封)
      const exp = await fetch(base + `/api/traces/${tid}/export`);
      assert.ok((exp.headers.get("Content-Disposition") ?? "").includes("attachment"));
      const envelope = await exp.json();
      assert.equal(envelope.resourceSpans[0].scopeSpans[0].spans.length, 3);

      // 生命周期
      const lc = await post(base, `/api/traces/${tid}/lifecycle`, { lifecycle: "done" });
      assert.equal(lc.status, 200);
    });
  });

  it("SSE stream established and receives decision_point", async () => {
    await withSession(async (session, base) => {
      const r = await fetch(base + "/api/events", { headers: { Accept: "text/event-stream" } });
      assert.equal(r.status, 200);
      const reader = r.body!.getReader();
      const first = await reader.read();
      assert.ok(new TextDecoder().decode(first.value).includes("connected"));

      const runner = makeRunner(session, ["s0"]);
      await session.trace(() => runner.run(1));

      const ev = (await Promise.race([
        reader.read(),
        new Promise((res) => setTimeout(() => res(null), 1500)),
      ])) as { value?: Uint8Array } | null;
      const text = ev?.value ? new TextDecoder().decode(ev.value) : "";
      assert.ok(text.includes("decision_point"), "expected decision_point SSE event, got: " + text);
      await reader.cancel();
    });
  });

  it("unknown api path -> 404, invalid body -> 422", async () => {
    await withSession(async (_s, base) => {
      assert.equal((await get(base, "/api/nope")).status, 404);
      const bad = await fetch(base + "/api/forks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "not-json",
      });
      assert.equal(bad.status, 422);
    });
  });
});
