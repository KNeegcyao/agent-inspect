// Live 调试门状态机测试(spec js-sdk.JS 运行时 Live 调试)。
import { assert, describe, it } from "./helpers.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store.js";
import { ForkController } from "../src/fork.js";
import { Interceptor } from "../src/interceptor.js";
import { DebugController } from "../src/debug.js";
import { Cursor, runWithCursor } from "../src/context.js";
import type { DebugGate } from "../src/debug.js";

function makeSetup() {
  const store = new Store(join(mkdtempSync(join(tmpdir(), "ai-dbg-")), "s.json"));
  const fork = new ForkController(store);
  const debug = new DebugController(store);
  const interceptor = new Interceptor(store, fork, undefined, debug);
  return { store, fork, debug, interceptor };
}

async function waitPaused(gate: DebugGate, step: number, timeout = 2000): Promise<void> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (gate.pausedAt === step) return;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error(`not paused at ${step}, state=${JSON.stringify(gate.state())}`);
}

// 把执行括进指定 trace 的 liveDebug 游标(等价 session.trace 内的执行)
function runInTrace(env: { interceptor: Interceptor; debug: DebugController }, traceId: string, branchId: string, fn: () => Promise<unknown>): Promise<unknown> {
  const cursor = new Cursor({ traceId, branchId, liveDebug: true });
  return runWithCursor(cursor, fn);
}

function oneStep(interceptor: Interceptor, scripted: string[], counter: { i: number; calls: number }, seen: unknown[] | null) {
  return interceptor.route({
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
    makeModifiedCall: seen
      ? (patched) => () => {
          seen.push(patched);
          return Promise.resolve("R");
        }
      : undefined,
  });
}

describe("debug gate", () => {
  it("breakpoint hit pauses with inspectable input; resume completes", async () => {
    const { store, debug, interceptor } = makeSetup();
    const created = store.createTraceWithRoot("agent");
    const gate = debug.ensureGate(created.trace.id);
    gate.attach();
    gate.addBreakpoint({ kind: "llm" });

    const counter = { i: 0, calls: 0 };
    const p = runInTrace({ interceptor, debug }, created.trace.id, created.branch.id, () =>
      oneStep(interceptor, ["s0"], counter, null),
    ); // 不 await:应停在断点
    await waitPaused(gate, 0);
    assert.equal(counter.calls, 0, "暂停点不得发起真实调用");
    const st = gate.state() as Record<string, unknown>;
    assert.equal(st["attached"], true);
    assert.equal(gate.pausedPayload!["step_index"], 0);

    gate.resume();
    await p;
    assert.equal(counter.calls, 1);
    assert.equal(gate.state()["paused_at"], null);
    store.close();
  });

  it("condition no-match completes without blocking", async () => {
    const { store, debug, interceptor } = makeSetup();
    const created = store.createTraceWithRoot("agent");
    const gate = debug.ensureGate(created.trace.id);
    gate.attach();
    gate.addBreakpoint({ condition: "never-present" });

    const counter = { i: 0, calls: 0 };
    const p = runInTrace({ interceptor, debug }, created.trace.id, created.branch.id, () =>
      oneStep(interceptor, ["s0"], counter, null),
    );
    await p; // 不暂停 → 直接完成
    assert.equal(counter.calls, 1);
    assert.equal(gate.state()["paused_at"], null);
    store.close();
  });

  it("step semantics + stale at_step ignored (duplicate delivery idempotent)", async () => {
    const { store, debug, interceptor } = makeSetup();
    const created = store.createTraceWithRoot("agent");
    const gate = debug.ensureGate(created.trace.id);
    gate.attach();
    gate.pause(); // 手动暂停:下一决策点边界生效

    const counter = { i: 0, calls: 0 };
    const p = runInTrace({ interceptor, debug }, created.trace.id, created.branch.id, async () => {
      for (const s of ["s0", "s1", "s2"]) await oneStep(interceptor, [s], counter, null);
    });
    await waitPaused(gate, 0);

    assert.equal(gate.step(0), true);
    await waitPaused(gate, 1); // 恰执行一个决策点后停下
    assert.equal(gate.step(0), false); // 过期指令(at_step 仍为旧暂停点)→ 忽略
    await new Promise((r) => setTimeout(r, 30));
    assert.equal(gate.state()["paused_at"], 1, "过期 step 不得放行新暂停点");

    assert.equal(gate.step(1), true);
    await waitPaused(gate, 2);
    assert.equal(gate.resume(2), true);
    await p;
    assert.equal(counter.calls, 3);
    store.close();
  });

  it("modify at paused point swaps real input; duplicate modify does not release next pause", async () => {
    const { store, debug, interceptor } = makeSetup();
    const created = store.createTraceWithRoot("agent");
    const gate = debug.ensureGate(created.trace.id);
    gate.attach();
    gate.addBreakpoint({ kind: "llm" }); // modify 放行后,step1 经断点再次暂停
    gate.pause();

    const counter = { i: 0, calls: 0 };
    const seen: unknown[] = [];
    const p = runInTrace({ interceptor, debug }, created.trace.id, created.branch.id, async () => {
      await oneStep(interceptor, ["s0"], counter, seen);
      await oneStep(interceptor, ["s1"], counter, seen);
    });
    await waitPaused(gate, 0);
    assert.equal(gate.modify(0, "messages[0].content", "EDITED"), true);
    await waitPaused(gate, 1);
    gate.modify(0, "messages[0].content", "EDITED"); // 重复投递(过期 step)→ 不误放
    await new Promise((r) => setTimeout(r, 30));
    assert.equal(gate.state()["paused_at"], 1, "重复 modify 不得误放后续暂停点");
    gate.resume();
    await p;

    assert.deepEqual(
      (seen[0] as Record<string, unknown>)["messages"],
      [{ role: "user", content: "EDITED" }],
    );
    // 落盘输入为修改后值
    const root = created.branch.id;
    const pts = store.getDecisionPoints(created.trace.id, created.branch.id);
    assert.deepEqual(
      (pts[0].input_context["messages"] as unknown[])[0],
      { role: "user", content: "EDITED" },
    );
    store.close();
  });

  it("breakpoints persist across controller/session", async () => {
    const store = new Store(join(mkdtempSync(join(tmpdir(), "ai-dbg2-")), "s.json"));
    const debug1 = new DebugController(store);
    const created = store.createTraceWithRoot("agent");
    const gate1 = debug1.ensureGate(created.trace.id);
    gate1.attach();
    const bp = gate1.addBreakpoint({ kind: "llm" });

    const debug2 = new DebugController(store);
    const gate2 = debug2.ensureGate(created.trace.id);
    assert.deepEqual(gate2.breakpoints, [bp]);
    store.close();
  });
});
