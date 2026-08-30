// Live 调试(Mode C):DebugGate(单 trace 状态机)+ DebugController(注册表)。
// 阻塞原语为 Promise resolver:暂停 = 登记 waiter 并 await;指令 = resolve。
// 释放指令绑定暂停点(at_step):重复/迟到投递被忽略(与 Python 修复后语义一致)。
import type { Breakpoint, DecisionPoint } from "./models.js";
import { newId, now } from "./models.js";
import type { Store } from "./store.js";

type ReleaseAction = "continue" | "step";

export interface PendingModify {
  step: number;
  field: string;
  value: unknown;
}

export class DebugGate {
  attached = false;
  breakpoints: Breakpoint[];
  pauseRequested = false;
  stepMode = false;
  pendingModify: PendingModify | null = null;
  pausedAt: number | null = null;
  pausedPayload: Record<string, unknown> | null = null;

  private waiter: (() => void) | null = null;
  private releaseAction: ReleaseAction | null = null;

  constructor(
    readonly traceId: string,
    private store: Store,
    private onEvent?: (event: string, payload: unknown) => void,
    breakpoints?: Breakpoint[],
  ) {
    this.breakpoints = breakpoints ?? store.listBreakpoints(traceId);
  }

  // ---- 拦截器咨询点(决策点边界,真实调用前) ----
  async consult(dp: DecisionPoint): Promise<PendingModify | null> {
    if (!this.attached) return null;
    if (!this.shouldPause(dp)) return null;
    this.pausedAt = dp.step_index;
    this.pausedPayload = {
      trace_id: dp.trace_id,
      branch_id: dp.branch_id,
      step_index: dp.step_index,
      kind: dp.kind,
      agent_id: dp.agent_id,
      input_context: dp.input_context,
      output: null,
    };
    this.onEvent?.("trace.paused", { ...this.pausedPayload });
    await new Promise<void>((resolve) => {
      this.waiter = resolve;
    });
    const action = this.releaseAction;
    this.releaseAction = null;
    this.pausedAt = null;
    this.pausedPayload = null;
    if (action === "step") this.stepMode = true;
    else this.stepMode = false;
    this.onEvent?.("trace.resumed", { trace_id: this.traceId, step_index: dp.step_index });
    const mod = this.takeModify(dp.step_index);
    return mod;
  }

  private shouldPause(dp: DecisionPoint): boolean {
    if (this.pauseRequested) {
      this.pauseRequested = false;
      return true;
    }
    if (this.stepMode) {
      this.stepMode = false;
      return true;
    }
    return this.breakpoints.some((bp) => bp.enabled && bpMatches(bp, dp));
  }

  private takeModify(step: number): PendingModify | null {
    const mod = this.pendingModify;
    this.pendingModify = null;
    return mod && mod.step === step ? mod : null;
  }

  // ---- 面板指令 ----
  attach(): boolean {
    if (this.attached) return false;
    this.attached = true;
    this.onEvent?.("trace.attached", { trace_id: this.traceId });
    return true;
  }

  addBreakpoint(opts: { kind?: string | null; agentId?: string | null; condition?: string | null }): Breakpoint {
    const bp: Breakpoint = {
      id: newId("bp"),
      trace_id: this.traceId,
      kind: opts.kind ?? null,
      agent_id: opts.agentId ?? null,
      condition: opts.condition ?? null,
      enabled: true,
      created_at: now(),
    };
    this.store.addBreakpoint(bp);
    this.breakpoints.push(bp);
    this.onEvent?.("breakpoint.set", { ...bp });
    return { ...bp };
  }

  removeBreakpoint(bpId: string): boolean {
    const before = this.breakpoints.length;
    this.breakpoints = this.breakpoints.filter((b) => b.id !== bpId);
    const removed = this.breakpoints.length < before;
    if (removed) {
      this.store.removeBreakpoint(this.traceId, bpId);
      this.onEvent?.("breakpoint.removed", { trace_id: this.traceId, breakpoint_id: bpId });
    }
    return removed;
  }

  pause(): void {
    this.pauseRequested = true;
  }

  step(atStep?: number | null): boolean {
    return this.issueRelease(atStep, "step");
  }

  resume(atStep?: number | null): boolean {
    return this.issueRelease(atStep, "continue");
  }

  // 放行;at_step 绑定暂停代际:不匹配当前暂停点则忽略(重复/迟到指令幂等)
  private issueRelease(atStep: number | null | undefined, action: ReleaseAction): boolean {
    if (atStep != null && this.pausedAt !== atStep) return false;
    this.releaseAction = action;
    const w = this.waiter;
    this.waiter = null;
    w?.();
    return true;
  }

  modify(step: number, field: string, value: unknown, action: ReleaseAction = "continue"): boolean {
    this.pendingModify = { step, field, value };
    // 放行绑定修改的目标 step:重复投递的 modify 不误放已前进到的其它暂停点
    if (this.pausedAt === step) {
      this.releaseAction = action;
      const w = this.waiter;
      this.waiter = null;
      w?.();
      return true;
    }
    return false;
  }

  state(): Record<string, unknown> {
    return {
      trace_id: this.traceId,
      attached: this.attached,
      paused_at: this.pausedAt,
      waiting: this.waiter !== null,
      breakpoints: this.breakpoints.map((b) => ({ ...b })),
    };
  }
}

function bpMatches(bp: Breakpoint, dp: DecisionPoint): boolean {
  if (bp.kind && dp.kind !== bp.kind) return false;
  if (bp.agent_id && !String(dp.agent_id).includes(bp.agent_id)) return false;
  if (bp.condition) {
    const hay = JSON.stringify(dp.input_context ?? {});
    if (!hay.includes(bp.condition)) return false;
  }
  return true;
}

export class DebugController {
  private gates = new Map<string, DebugGate>();

  constructor(private store: Store, private onEvent?: (event: string, payload: unknown) => void) {}

  ensureGate(traceId: string): DebugGate {
    let gate = this.gates.get(traceId);
    if (!gate) {
      gate = new DebugGate(traceId, this.store, this.onEvent);
      this.gates.set(traceId, gate);
    }
    return gate;
  }

  gate(traceId: string): DebugGate | null {
    return this.gates.get(traceId) ?? null;
  }

  // 拦截器决策点边界入口:按 trace 路由到对应门(未附加即零开销放行)
  consult(traceId: string, dp: DecisionPoint): Promise<PendingModify | null> {
    return this.ensureGate(traceId).consult(dp);
  }
}
