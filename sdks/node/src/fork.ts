// Fork 引擎:发起校验、待执行队列、按分支注入修改表。
import type { Store } from "./store.js";
import type { Branch } from "./models.js";

export interface Modification {
  step: number;
  field: string; // "output" 或 "input_context.<路径>"
  value: unknown;
}

export interface ForkPlan {
  traceId: string;
  branchId: string;
  originBranch: string;
  branchFromStep: number;
  dryRun: boolean;
  modifications: Modification[];
  sandbox: Record<string, string> | null;
}

export class ForkError extends Error {}

export const BIG_STEP = 2 ** 31;

// 副作用沙箱:按决策点类型配置执行策略(spec js-sdk.副作用沙箱)
export const SANDBOX_KINDS = ["llm", "tool"];
export const SANDBOX_POLICIES = ["allow", "dry-run", "block"];

export class ForkController {
  private pending: ForkPlan[] = [];
  private mods = new Map<string, Modification[]>();

  constructor(private store: Store) {}

  async requestFork(opts: {
    traceId: string;
    fromBranch: string;
    fromStep: number;
    modifications?: Modification[];
    dryRun?: boolean;
    note?: string | null;
    sandbox?: Record<string, string> | null;
  }): Promise<{ branch: Branch; plan: ForkPlan }> {
    const { traceId, fromBranch, fromStep } = opts;
    const sandbox = opts.sandbox ?? null;
    if (sandbox) {
      for (const [kind, policy] of Object.entries(sandbox)) {
        if (!SANDBOX_KINDS.includes(kind)) throw new ForkError(`invalid sandbox kind: ${kind}`);
        if (!SANDBOX_POLICIES.includes(policy)) {
          throw new ForkError(`invalid sandbox policy ${policy} for kind ${kind}`);
        }
      }
    }
    if (this.store.countDecisionPoints(traceId) === 0) {
      throw new ForkError(
        `cannot fork empty trace ${traceId}: no decision points recorded yet`,
      );
    }
    const parent = this.store.getBranch(fromBranch);
    if (!parent) throw new ForkError(`cannot fork: branch ${fromBranch} not found`);
    if (parent.trace_id !== traceId) {
      throw new ForkError(
        `cannot fork: branch ${fromBranch} belongs to trace ${parent.trace_id}, not target trace ${traceId}`,
      );
    }
    const last = this.store.lastStepBefore(fromBranch, BIG_STEP) ?? 0;
    if (fromStep < 0 || fromStep > last + 1) {
      throw new ForkError(
        `fork step ${fromStep} out of range for branch ${fromBranch} (0..${last + 1})`,
      );
    }
    const branch = this.store.createBranch(
      traceId,
      fromBranch,
      fromStep,
      "fork",
      opts.note ?? null,
    );
    const modifications = opts.modifications ?? [];
    this.mods.set(branch.id, modifications);
    const plan: ForkPlan = {
      traceId,
      branchId: branch.id,
      originBranch: fromBranch,
      branchFromStep: fromStep,
      dryRun: opts.dryRun ?? false,
      modifications,
      sandbox,
    };
    this.pending.push(plan);
    return { branch, plan };
  }

  consumePendingFork(): ForkPlan | null {
    return this.pending.shift() ?? null;
  }

  modificationFor(branchId: string, step: number): Modification | null {
    return (this.mods.get(branchId) ?? []).find((m) => m.step === step) ?? null;
  }
}
