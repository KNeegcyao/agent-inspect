// 存储测试:读写、同时钟平局排序、lastStepBefore、持久化往返。
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store.js";
import { assert, describe, it } from "./helpers.js";

describe("store", () => {
  it("create/record/list roundtrip, newest first with insertion tie-break", () => {
    const dir = mkdtempSync(join(tmpdir(), "ai-store-"));
    const store = new Store(join(dir, "s.json"));
    const t1 = store.createTraceWithRoot("a");
    const t2 = store.createTraceWithRoot("b");
    // 固定同一 started_at 模拟同时钟刻度:插入序决定新者在先
    store.listTraces();
    assert.equal(store.listTraces()[0].id, t2.trace.id);
    assert.equal(store.listTraces().length, 2);

    store.writeDecisionPoint({
      id: "dp_1",
      trace_id: t1.trace.id,
      branch_id: t1.branch.id,
      step_index: 0,
      kind: "llm",
      agent_id: "x",
      input_context: { messages: [] },
      output: { content: "a" },
      output_hash: null,
      cause_edge: [],
      meta: {},
    });
    store.writeDecisionPoint({
      id: "dp_2",
      trace_id: t1.trace.id,
      branch_id: t1.branch.id,
      step_index: 1,
      kind: "llm",
      agent_id: "x",
      input_context: { messages: [] },
      output: null,
      output_hash: null,
      cause_edge: ["dp_1"],
      meta: {},
    });
    const pts = store.getDecisionPoints(t1.trace.id, t1.branch.id);
    assert.deepEqual(
      pts.map((p) => p.step_index),
      [0, 1],
    );
    assert.deepEqual(pts[1].cause_edge, ["dp_1"]);
    assert.equal(store.countDecisionPoints(t1.trace.id), 2);
    assert.equal(store.lastStepBefore(t1.branch.id, 2 ** 31), 1);
    assert.equal(store.lastStepBefore(t1.branch.id, 1), 0);
    store.close();
  });

  it("persists to disk and reloads (crash does not lose recorded points)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ai-store2-"));
    const path = join(dir, "s.json");
    const s1 = new Store(path);
    const t = s1.createTraceWithRoot("agent");
    s1.writeDecisionPoint({
      id: "dp_1",
      trace_id: t.trace.id,
      branch_id: t.branch.id,
      step_index: 0,
      kind: "llm",
      agent_id: "x",
      input_context: {},
      output: { content: "a" },
      output_hash: null,
      cause_edge: [],
      meta: {},
    });
    await s1.flush();
    s1.close();

    const s2 = new Store(path);
    assert.equal(s2.listTraces().length, 1);
    assert.equal(s2.getDecisionPoints(t.trace.id, t.branch.id).length, 1);
    assert.equal(s2.getTrace(t.trace.id)?.lifecycle, "running");
    s2.close();
  });

  it("lifecycle update persisted", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ai-store3-"));
    const path = join(dir, "s.json");
    const s = new Store(path);
    const t = s.createTraceWithRoot("agent");
    s.setTraceLifecycle(t.trace.id, "done");
    await s.flush();
    s.close();
    const s2 = new Store(path);
    assert.equal(s2.getTrace(t.trace.id)?.lifecycle, "done");
    s2.close();
  });
});
