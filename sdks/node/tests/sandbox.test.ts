// 副作用沙箱测试(spec js-sdk.JS 运行时副作用沙箱)。
import { assert, describe, it } from "./helpers.js";
import { closeEnv, makeEnv, runDetached, runWithCursor } from "./helpers.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Cursor } from "../src/context.js";
import { ForkError, SANDBOX_KINDS, SANDBOX_POLICIES } from "../src/fork.js";
import { start, type Session } from "../src/session.js";
import type { Interceptor } from "../src/interceptor.js";

interface Counter {
  i: number;
  calls: number;
}

function runKind(
  interceptor: Interceptor,
  kind: "llm" | "tool",
  counter: Counter,
): Promise<unknown> {
  return interceptor.route({
    kind,
    agentId: "fake-" + kind,
    inputContext: { messages: [], model: "fake", params: {} },
    call: () => {
      counter.calls += 1;
      return Promise.resolve("REAL");
    },
    reconstruct: (d) => (d ? (d["content"] as string) : null),
    shapeOutput: (x) => ({ content: x }),
  });
}

async function seedTwoStep(env: { store: any; interceptor: Interceptor }) {
  const counter: Counter = { i: 0, calls: 0 };
  for (let k = 0; k < 2; k++) {
    await env.interceptor.route({
      kind: "llm",
      agentId: "fake-llm",
      inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
      call: () => {
        counter.calls += 1;
        const v = counter.i < 2 ? ["a", "b"][counter.i] : null;
        counter.i += 1;
        return Promise.resolve(v);
      },
      reconstruct: (d) => (d ? (d["content"] as string) : null),
      shapeOutput: (x) => ({ content: x }),
    });
  }
  const trace = env.store.listTraces()[0];
  const root = env.store.listBranches(trace.id)[0];
  return { trace, root, counter };
}

function forkCursor(
  traceId: string,
  branchId: string,
  rootId: string,
  sandbox: Record<string, string>,
) {
  return new Cursor({
    traceId,
    branchId,
    mode: "fork",
    replayBranchId: rootId,
    sandbox,
  });
}

describe("side-effect sandbox", () => {
  it("tool dry-run: no real call, meta marked; llm unconfigured really calls", async () => {
    const env = makeEnv();
    try {
      const { trace, root, counter } = await seedTwoStep(env);
      const { branch } = await env.fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 0,
        sandbox: { tool: "dry-run" },
      });
      await runDetached(async () => {
        await runWithCursor(forkCursor(trace.id, branch.id, root.id, { tool: "dry-run" }), async () => {
          const t1 = await runKind(env.interceptor, "tool", counter);
          assert.equal(t1, null, "dry-run 输出为空");
          const l1 = await runKind(env.interceptor, "llm", counter);
          assert.equal(l1, "REAL", "llm 未配置照常真调");
        });
      });
      assert.equal(counter.calls, 3, "种子 2 次 + llm 真调 1 次(tool 被拦)");
      const pts = env.store.getDecisionPoints(trace.id, branch.id);
      const toolPt = pts.find((p) => p.kind === "tool")!;
      const llmPt = pts.find((p) => p.kind === "llm")!;
      assert.equal(toolPt.meta["sandbox"], "dry-run");
      assert.equal("sandbox" in llmPt.meta, false);
    } finally {
      closeEnv(env);
    }
  });

  it("tool block: no real call, meta blocked", async () => {
    const env = makeEnv();
    try {
      const { trace, root, counter } = await seedTwoStep(env);
      const { branch } = await env.fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 0,
        sandbox: { tool: "block" },
      });
      await runDetached(async () => {
        await runWithCursor(forkCursor(trace.id, branch.id, root.id, { tool: "block" }), async () => {
          const out = await runKind(env.interceptor, "tool", counter);
          assert.equal(out, null);
        });
      });
      assert.equal(counter.calls, 2, "仅种子调用(tool 被拦)");
      const pts = env.store.getDecisionPoints(trace.id, branch.id);
      assert.equal(pts.find((p) => p.kind === "tool")!.meta["sandbox"], "blocked");
    } finally {
      closeEnv(env);
    }
  });

  it("mixed {llm: block, tool: allow}: llm blocked, tool really calls", async () => {
    const env = makeEnv();
    try {
      const { trace, root, counter } = await seedTwoStep(env);
      const { branch } = await env.fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 0,
        sandbox: { llm: "block", tool: "allow" },
      });
      await runDetached(async () => {
        await runWithCursor(
          forkCursor(trace.id, branch.id, root.id, { llm: "block", tool: "allow" }),
          async () => {
            const l = await runKind(env.interceptor, "llm", counter);
            assert.equal(l, null);
            const t = await runKind(env.interceptor, "tool", counter);
            assert.equal(t, "REAL");
          },
        );
      });
      assert.equal(counter.calls, 3, "种子 2 次 + tool 真调 1 次(llm 被拦)");
    } finally {
      closeEnv(env);
    }
  });

  it("invalid kind/policy rejected without writing", async () => {
    const env = makeEnv();
    try {
      const { trace, root } = await seedTwoStep(env);
      await assert.rejects(
        env.fork.requestFork({
          traceId: trace.id,
          fromBranch: root.id,
          fromStep: 0,
          sandbox: { memory: "block" },
        }),
        /invalid sandbox kind/,
      );
      await assert.rejects(
        env.fork.requestFork({
          traceId: trace.id,
          fromBranch: root.id,
          fromStep: 0,
          sandbox: { tool: "bogus" },
        }),
        /invalid sandbox policy/,
      );
      assert.equal(env.store.listBranches(trace.id).length, 1);
    } finally {
      closeEnv(env);
    }
  });

  it("sandbox constants match contract", () => {
    assert.deepEqual(SANDBOX_KINDS, ["llm", "tool"]);
    assert.deepEqual(SANDBOX_POLICIES, ["allow", "dry-run", "block"]);
  });
});

describe("sandbox over HTTP", () => {
  it("fork with sandbox: meta marks on disk, no real calls, invalid 422", async () => {
    const s = await start({
      dbPath: join(mkdtempSync(join(tmpdir(), "ai-sbx-")), "s.json"),
      port: 0,
      autostartBrowser: false,
    });
    try {
      const base = s.url;
      const counter: Counter = { i: 0, calls: 0 };
      const toolRoute = () =>
        s.interceptor.route({
          kind: "tool",
          agentId: "fake-tool",
          inputContext: { tool: "t", args: {}, messages: [], model: "fake", params: {} },
          call: () => {
            counter.calls += 1;
            return Promise.resolve("v" + counter.i);
          },
          reconstruct: (d) => (d ? (d["result"] as string) : null),
          shapeOutput: (x) => ({ result: x }),
        });

      // 录制:两个工具决策点
      await s.trace(async () => {
        await toolRoute();
        await toolRoute();
      });
      assert.equal(counter.calls, 2);

      const { body: traces } = await req(s.url, "GET", "/api/traces");
      const tid = traces[0].id;
      const { body: detail } = await req(s.url, "GET", `/api/traces/${tid}`);
      const root = detail.trace.root_branch_id;

      // 携带 sandbox 发起 Fork
      const fk = await req(s.url, "POST", "/api/forks", {
        trace_id: tid,
        branch_id: root,
        from_step: 0,
        sandbox: { tool: "dry-run" },
      });
      assert.equal(fk.status, 200, JSON.stringify(fk.body));
      const forkBranch = fk.body.branch.id;

      // 执行 Fork:工具 dry-run 不真调
      const callsBefore = counter.calls;
      await s.trace(async () => {
        await toolRoute();
        await toolRoute();
      });
      assert.equal(counter.calls, callsBefore, "沙箱拦截不得真调");

      const { body: fpts } = await req(s.url, "GET", `/api/branches/${forkBranch}/points`);
      assert.equal(fpts.length, 2);
      assert.equal(fpts.every((p: any) => p.meta.sandbox === "dry-run"), true);

      // 非法配置 → 422 且无新分支
      const bad = await req(s.url, "POST", "/api/forks", {
        trace_id: tid,
        branch_id: root,
        from_step: 0,
        sandbox: { tool: "bogus" },
      });
      assert.equal(bad.status, 422);
      const { body: branches } = await req(s.url, "GET", `/api/traces/${tid}`);
      assert.equal(branches.branches.length, 2);
    } finally {
      await s.stop();
    }
  });
});

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
