// Fork 引擎测试:发起边界、注入修改、前缀回放、只读预览(spec js-sdk.Fork)。
import { makeEnv, closeEnv, runSteps, runDetached, assert, describe, it } from "./helpers.js";
import { ForkError } from "../src/fork.js";

describe("fork engine", () => {
  it("rejects empty trace / out-of-range / wrong-trace branch without writing", async () => {
    const env = makeEnv();
    try {
      const empty = env.store.createTraceWithRoot("empty");
      await assert.rejects(
        env.fork.requestFork({ traceId: empty.trace.id, fromBranch: empty.branch.id, fromStep: 0 }),
        /empty trace/,
      );
      assert.equal(env.store.listBranches(empty.trace.id).length, 1);

      const { store, fork } = env;
      await runSteps(env.interceptor, 2, ["a", "b"]);
      const trace = store.listTraces()[0];
      const root = store.listBranches(trace.id)[0];
      await assert.rejects(
        fork.requestFork({ traceId: trace.id, fromBranch: root.id, fromStep: 99 }),
        /out of range/,
      );
      await assert.rejects(
        fork.requestFork({ traceId: trace.id, fromBranch: "br_nope", fromStep: 0 }),
        /not found/,
      );
      // 另一条 trace 的分支归属校验
      await runDetached(async () => {
        await runSteps(env.interceptor, 1, ["x"]);
      });
      const traces = store.listTraces();
      const other = traces[0].id === trace.id ? traces[1] : traces[0];
      const otherRoot = store.listBranches(other.id)[0];
      await assert.rejects(
        fork.requestFork({ traceId: trace.id, fromBranch: otherRoot.id, fromStep: 0 }),
        /belongs to trace/,
      );
      assert.equal(store.listBranches(trace.id).length, 1);
    } finally {
      closeEnv(env);
    }
  });

  it("fork consumption: prefix replayed without real calls, suffix really runs on new branch", async () => {
    const env = makeEnv();
    try {
      const { store, fork, interceptor } = env;
      await runSteps(interceptor, 3, ["a", "b", "c"]);
      const trace = store.listTraces()[0];
      const root = store.listBranches(trace.id)[0];

      const { branch } = await fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 1,
        note: "t",
      });
      assert.equal(branch.origin, "fork");
      assert.equal(branch.branch_from_step, 1);

      let calls = 0;
      await runDetached(async () => {
        const state = { i: 0 };
        const outs: (string | null)[] = [];
        for (let k = 0; k < 3; k++) {
          outs.push(
            (await interceptor.route({
              kind: "llm",
              agentId: "fake-llm",
              inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
              call: () => {
                calls += 1;
                const v = state.i < 1 ? ["X"][state.i] : null;
                state.i += 1;
                return Promise.resolve(v);
              },
              reconstruct: (d) => (d ? (d["content"] as string) : null),
              shapeOutput: (x) => ({ content: x }),
            })) as string | null,
          );
        }
        // step0 回放原始 a;step1 真调 X;step2 真调(脚本耗尽 → null)
        assert.deepEqual(outs, ["a", "X", null]);
      });
      assert.equal(calls, 2, "suffix steps really call (step2 script exhausted → null)");

      const fpts = store.getDecisionPoints(trace.id, branch.id);
      // 前缀共享:fork 分支只存后缀真实执行的点(step1 起)
      assert.deepEqual(fpts.map((p) => p.step_index), [1, 2]);
      assert.equal(fpts[0].output && (fpts[0].output as Record<string, unknown>)["content"], "X");
      assert.equal(fpts[1].cause_edge.length, 1);
    } finally {
      closeEnv(env);
    }
  });

  it("inject output: no real call, injected value lands", async () => {
    const env = makeEnv();
    try {
      const { store, fork, interceptor } = env;
      await runSteps(interceptor, 2, ["a", "b"]);
      const trace = store.listTraces()[0];
      const root = store.listBranches(trace.id)[0];
      await fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 0,
        modifications: [{ step: 0, field: "output", value: { result: "FAKE" } }],
      });
      let calls = 0;
      await runDetached(async () => {
        const out = await interceptor.route({
          kind: "llm",
          agentId: "fake-llm",
          inputContext: { messages: [], model: "fake", params: {} },
          call: () => {
            calls += 1;
            return Promise.resolve("SHOULD_NOT");
          },
          reconstruct: (d) => d,
          shapeOutput: (x) => x as Record<string, unknown>,
        });
        assert.deepEqual(out, { result: "FAKE" });
      });
      assert.equal(calls, 0);
    } finally {
      closeEnv(env);
    }
  });

  it("inject input path: real call sees patched input, stored input is patched", async () => {
    const env = makeEnv();
    try {
      const { store, fork, interceptor } = env;
      await runSteps(interceptor, 2, ["a", "b"]);
      const trace = store.listTraces()[0];
      const root = store.listBranches(trace.id)[0];
      await fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 0,
        modifications: [
          { step: 0, field: "input_context.messages[0].content", value: "INJECTED" },
        ],
      });
      let seen: unknown = null;
      await runDetached(async () => {
        await interceptor.route({
          kind: "llm",
          agentId: "fake-llm",
          inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
          call: () => Promise.resolve("R"),
          reconstruct: (d) => d,
          shapeOutput: (x) => ({ content: x }),
          makeModifiedCall: (patched) => () => {
            seen = patched;
            return Promise.resolve("R");
          },
        });
      });
      assert.deepEqual(
        (seen as Record<string, unknown>)["messages"],
        [{ role: "user", content: "INJECTED" }],
      );
      const pts = store.getDecisionPoints(trace.id, store.listBranches(trace.id)[1].id);
      assert.deepEqual(
        (pts[0].input_context["messages"] as unknown[])[0],
        { role: "user", content: "INJECTED" },
      );
    } finally {
      closeEnv(env);
    }
  });

  it("dry run: suffix never really calls, outputs empty", async () => {
    const env = makeEnv();
    try {
      const { store, fork, interceptor } = env;
      await runSteps(interceptor, 2, ["a", "b"]);
      const trace = store.listTraces()[0];
      const root = store.listBranches(trace.id)[0];
      await fork.requestFork({
        traceId: trace.id,
        fromBranch: root.id,
        fromStep: 0,
        dryRun: true,
      });
      let calls = 0;
      await runDetached(async () => {
        const out = await interceptor.route({
          kind: "llm",
          agentId: "fake-llm",
          inputContext: { messages: [], model: "fake", params: {} },
          call: () => {
            calls += 1;
            return Promise.resolve("REAL");
          },
          reconstruct: (d) => (d ? (d["content"] as string) : null),
          shapeOutput: (x) => ({ content: x }),
        });
        assert.equal(out, null); // reconstruct(null) → 空
      });
      assert.equal(calls, 0);
    } finally {
      closeEnv(env);
    }
  });

  it("nested fork: prefix walks up the parent branch chain", async () => {
    const env = makeEnv();
    try {
      const { store, fork, interceptor } = env;
      await runSteps(interceptor, 3, ["a", "b", "c"]);
      const trace = store.listTraces()[0];
      const root = store.listBranches(trace.id)[0];
      const f1 = await fork.requestFork({ traceId: trace.id, fromBranch: root.id, fromStep: 1 });
      await runDetached(async () => {
        await runSteps(interceptor, 3, ["X", "Y"]);
      });
      // 从 f1 的产物再 fork:from_step=2 → step0/1 沿父链回放(a、X),step2 真调
      const f2 = await fork.requestFork({
        traceId: trace.id,
        fromBranch: f1.branch.id,
        fromStep: 2,
      });
      await runDetached(async () => {
        const outs: (string | null)[] = [];
        for (let k = 0; k < 3; k++) {
          outs.push(
            (await interceptor.route({
              kind: "llm",
              agentId: "fake-llm",
              inputContext: { messages: [], model: "fake", params: {} },
              call: () => Promise.resolve("Z"),
              reconstruct: (d) => (d ? (d["content"] as string) : null),
              shapeOutput: (x) => ({ content: x }),
            })) as string | null,
          );
        }
        assert.deepEqual(outs, ["a", "X", "Z"]);
      });
      assert.equal(store.listBranches(trace.id).length, 3);
    } finally {
      closeEnv(env);
    }
  });
});
