// 三态路由(record/replay/fork)+ 决策点登记落盘 + 注入路径补丁。
// 与 Python 侧 interceptor/base.py 同构:一个引擎,三种模式只是三种游标。
import { getCursor, enterCursor, Cursor, MODE_FORK, MODE_REPLAY } from "./context.js";
import type { DebugController } from "./debug.js";
import type { ForkController, Modification } from "./fork.js";
import type { DecisionPoint } from "./models.js";
import { hashOf, newId, now } from "./models.js";
import type { Store } from "./store.js";

export interface RouteOptions {
  kind: "llm" | "tool";
  agentId: string;
  inputContext: Record<string, unknown>;
  call: () => Promise<unknown> | unknown;
  reconstruct: (output: Record<string, unknown> | null) => unknown;
  shapeOutput: (native: unknown) => Record<string, unknown>;
  makeModifiedCall?: (patchedInput: Record<string, unknown>) => () => Promise<unknown> | unknown;
}

interface DecideResult {
  native: unknown;
  needsRecord: boolean;
}

export class Interceptor {
  constructor(
    private store: Store,
    private fork: ForkController,
    private onEvent?: (event: string, payload: unknown) => void,
    private debug?: DebugController,
  ) {}

  // 无活跃上下文:消费待执行 Fork,否则新建 record trace(进入当前异步上下文)
  acquireContext(): { cursor: Cursor; traceId: string; branchId: string } {
    const plan = this.fork.consumePendingFork();
    if (plan) {
      const cursor = new Cursor({
        traceId: plan.traceId,
        branchId: plan.branchId,
        mode: MODE_FORK,
        replayBranchId: plan.originBranch,
        branchFromStep: plan.branchFromStep,
        dryRun: plan.dryRun,
      });
      cursor.lastDpId = this.prefixLastDp(plan.traceId, plan.originBranch, plan.branchFromStep);
      enterCursor(cursor);
      return { cursor, traceId: plan.traceId, branchId: plan.branchId };
    }
    const { trace, branch } = this.store.createTraceWithRoot("agent");
    const cursor = new Cursor({
      traceId: trace.id,
      branchId: branch.id,
      liveDebug: !!this.debug,
    });
    enterCursor(cursor);
    if (this.debug) this.debug.ensureGate(trace.id);
    this.onEvent?.("trace.started", { trace_id: trace.id });
    return { cursor, traceId: trace.id, branchId: branch.id };
  }

  private ensureCursor(): Cursor {
    return getCursor() ?? this.acquireContext().cursor;
  }

  async route(opts: RouteOptions): Promise<unknown> {
    const cursor = this.ensureCursor();
    const step = cursor.nextStep();
    const dp: DecisionPoint = {
      id: newId("dp"),
      trace_id: cursor.traceId,
      branch_id: cursor.branchId,
      step_index: step,
      kind: opts.kind,
      agent_id: opts.agentId,
      input_context: opts.inputContext,
      output: null,
      output_hash: null,
      cause_edge: cursor.lastDpId ? [cursor.lastDpId] : [],
      meta: {},
    };
    // Mode C live 调试:决策点边界咨询调试门;命中 → 暂停等待指令,放行时应用替换输入
    let call = opts.call;
    if (cursor.liveDebug && this.debug) {
      const mod = await this.debug.consult(dp.trace_id, dp);
      if (mod) {
        this.applyInputMod(dp, mod);
        if (opts.makeModifiedCall) {
          const mk = opts.makeModifiedCall;
          call = () => mk(dp.input_context)();
        }
      }
    }
    const start = performance.now();
    let err: unknown = null;
    let native: unknown = null;
    let needsRecord = true;
    try {
      const r = await this.decide(cursor, step, dp, { ...opts, call });
      native = r.native;
      needsRecord = r.needsRecord;
    } catch (e) {
      err = e;
      dp.meta["error"] = {
        code: (e as Error)?.name ?? "Error",
        message: String((e as Error)?.message ?? e),
      };
    }
    this.finalize(dp, native, needsRecord, start, opts.shapeOutput);
    if (needsRecord) cursor.lastDpId = dp.id;
    if (err !== null) throw err;
    return native;
  }

  // ---- 模式路由(三态共享) ----
  private async decide(
    cursor: Cursor,
    step: number,
    dp: DecisionPoint,
    opts: RouteOptions,
  ): Promise<DecideResult> {
    if (cursor.mode === MODE_REPLAY) {
      const rec = this.recorded(cursor, step);
      if (rec) return { native: opts.reconstruct(rec), needsRecord: false };
      return { native: await opts.call(), needsRecord: true };
    }
    if (cursor.mode === MODE_FORK) {
      if (step < cursor.branchFromStep) {
        const rec = this.recorded(cursor, step);
        if (rec) return { native: opts.reconstruct(rec), needsRecord: false };
        return { native: await opts.call(), needsRecord: true };
      }
      const mod = this.fork.modificationFor(cursor.branchId, step);
      if (mod && mod.field === "output") {
        return { native: mod.value, needsRecord: true }; // 注入输出:不真调
      }
      if (mod && mod.field.startsWith("input_context")) {
        this.applyInputMod(dp, mod);
        if (opts.makeModifiedCall) {
          // 以替换后的 call 替换真实调用
          const modified = opts.makeModifiedCall(dp.input_context);
          return { native: await modified(), needsRecord: true };
        }
      }
      if (cursor.dryRun) {
        return { native: opts.reconstruct(null), needsRecord: true }; // 只读预览:不真调
      }
      return { native: await opts.call(), needsRecord: true };
    }
    return { native: await opts.call(), needsRecord: true };
  }

  // 沿分支父链向上找已记录输出(嵌套 Fork 前缀复用父分支记录)
  private recorded(cursor: Cursor, step: number): Record<string, unknown> | null {
    let branchId: string | null = cursor.replayBranchId ?? cursor.branchId;
    const seen = new Set<string>();
    while (branchId && !seen.has(branchId)) {
      seen.add(branchId);
      const dp = this.store.getDecisionPoint(cursor.traceId, branchId, step);
      if (dp && dp.output !== null) return dp.output;
      const branch = this.store.getBranch(branchId);
      branchId = branch ? branch.parent_branch_id : null;
    }
    return null;
  }

  prefixLastDp(traceId: string, branchId: string, branchFromStep: number): string | null {
    const points = this.store.getDecisionPoints(traceId, branchId, 0, branchFromStep - 1);
    return points.length ? points[points.length - 1].id : null;
  }

  // ---- 注入路径补丁:field = "input_context.<路径>"(支持点分与 [n] 下标) ----
  private applyInputMod(dp: DecisionPoint, mod: Modification): void {
    const raw = mod.field.startsWith("input_context.")
      ? mod.field.slice("input_context.".length)
      : mod.field;
    setPath(dp.input_context, splitKeyPath(raw), mod.value);
  }

  // ---- 收尾:填输出/meta + 落盘 ----
  private finalize(
    dp: DecisionPoint,
    native: unknown,
    needsRecord: boolean,
    start: number,
    shapeOutput: RouteOptions["shapeOutput"],
  ): void {
    if (native !== null && native !== undefined) {
      try {
        dp.output = shapeOutput(native);
      } catch {
        dp.output = { raw: String(native) };
      }
      dp.output_hash = hashOf(dp.output);
    }
    dp.meta["latency_ms"] = Math.round((performance.now() - start) * 100) / 10;
    dp.meta["ts"] = new Date().toISOString().replace(/\.\d+Z$/, "Z");
    if (needsRecord) {
      this.store.writeDecisionPoint(dp);
      this.onEvent?.("decision_point", { ...dp });
    }
  }
}

// ---- 路径补丁(与 Python 同语义:先按 "." 分段,再展开每段的 [n] 下标) ----
const BRACKET = /([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]/;

export function splitKeyPath(field: string): (string | number)[] {
  const keys: (string | number)[] = [];
  for (const seg of field.split(".")) {
    keys.push(...splitBracket(seg));
  }
  return keys;
}

function splitBracket(key: string): (string | number)[] {
  const parts: (string | number)[] = [];
  let pos = 0;
  const m = BRACKET.exec(key);
  if (m) {
    if (m.index > pos) parts.push(key.slice(pos, m.index));
    parts.push(m[1]);
    parts.push(Number(m[2]));
    pos = m.index + m[0].length;
  }
  if (pos < key.length) parts.push(key.slice(pos));
  return parts.length ? parts : [key];
}

export function setPath(obj: Record<string, unknown>, path: (string | number)[], value: unknown): void {
  let target: any = obj;
  for (let i = 0; i < path.length - 1; i++) {
    const p = path[i];
    const nextIsIndex = typeof path[i + 1] === "number";
    let nxt: any;
    if (typeof p === "number") {
      while (Array.isArray(target) && target.length <= p) target.push(null);
      nxt = target[p];
    } else {
      nxt = target[p];
    }
    if (nxt === null || nxt === undefined || typeof nxt !== "object") {
      nxt = nextIsIndex ? [] : {};
      target[p] = nxt;
    }
    target = nxt;
  }
  const k = path[path.length - 1];
  if (typeof k === "number") {
    while (Array.isArray(target) && target.length <= k) target.push(null);
    target[k] = value;
  } else {
    target[k] = value;
  }
}
