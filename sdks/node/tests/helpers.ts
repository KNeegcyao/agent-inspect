// 共享测试设施:离线确定性 Agent 执行辅助。
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store.js";
import { ForkController } from "../src/fork.js";
import { Interceptor } from "../src/interceptor.js";
import { runWithCursor } from "../src/context.js";

export interface Env {
  store: Store;
  fork: ForkController;
  interceptor: Interceptor;
  dir: string;
}

export function makeEnv(): Env {
  const dir = mkdtempSync(join(tmpdir(), "ai-sdk-test-"));
  const store = new Store(join(dir, "test.json"));
  const fork = new ForkController(store);
  const interceptor = new Interceptor(store, fork);
  return { store, fork, interceptor, dir };
}

export function closeEnv(env: Env): void {
  env.store.close();
  rmSync(env.dir, { recursive: true, force: true });
}

// 顺序执行 n 个 LLM 决策点;返回输出列表与真实调用计数(确定性脚本化模型)
export async function runSteps(
  interceptor: Interceptor,
  nSteps: number,
  scripted: string[],
): Promise<{ outs: (string | null)[]; calls: number }> {
  const state = { calls: 0, i: 0 };
  const outs: (string | null)[] = [];
  for (let k = 0; k < nSteps; k++) {
    outs.push(
      (await interceptor.route({
        kind: "llm",
        agentId: "fake-llm",
        inputContext: { messages: [{ role: "user", content: "hi" }], model: "fake", params: {} },
        call: () => {
          state.calls += 1;
          const v = state.i < scripted.length ? scripted[state.i] : null;
          state.i += 1;
          return Promise.resolve(v);
        },
        reconstruct: (d) => (d ? (d["content"] as string) : null),
        shapeOutput: (x) => ({ content: x }),
      })) as string | null,
    );
  }
  return { outs, calls: state.calls };
}

// 清空游标后执行(下一次 route 自取上下文:消费 pending fork 或新建 trace)
export function runDetached(fn: () => Promise<void>): Promise<void> {
  return runWithCursor(null, fn);
}

export { assert, describe, it };
