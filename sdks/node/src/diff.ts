// 分支 diff(对齐步骤 + 字段级明细 + 汇总)与采纳预览(差异 → 修改清单)。
// 纯只读计算,与 Python diff.py / adopt.py 同契约。
import type { Store } from "./store.js";
import type { DecisionPoint } from "./models.js";

export interface FieldDiff {
  path: string;
  left: unknown;
  right: unknown;
  status: "changed" | "added" | "removed";
}

export interface StepDiff {
  step_index: number;
  status: "same" | "diff" | "only_left" | "only_right";
  fields: FieldDiff[];
}

export interface DiffResult {
  branch_a: string;
  branch_b: string;
  steps: StepDiff[];
  summary: { same: number; diff: number; only_left: number; only_right: number };
}

export function diffBranches(store: Store, branchA: string, branchB: string): DiffResult {
  const ba = store.getBranch(branchA);
  const bb = store.getBranch(branchB);
  if (!ba || !bb) throw new DiffError("branch not found");
  const ta = store.listBranches(ba.trace_id);
  void ta;
  const a = store.getDecisionPoints(ba.trace_id, branchA);
  const b = store.getDecisionPoints(bb.trace_id, branchB);
  const maxLen = Math.max(a.length, b.length);
  const steps: StepDiff[] = [];
  const summary = { same: 0, diff: 0, only_left: 0, only_right: 0 };
  for (let i = 0; i < maxLen; i++) {
    const l = a[i];
    const r = b[i];
    if (l && r) {
      const fields = diffPoint(l, r);
      const status = fields.length ? "diff" : "same";
      summary[status] += 1;
      steps.push({ step_index: i, status, fields });
    } else if (l) {
      summary.only_left += 1;
      steps.push({ step_index: i, status: "only_left", fields: [] });
    } else {
      summary.only_right += 1;
      steps.push({ step_index: i, status: "only_right", fields: [] });
    }
  }
  return { branch_a: branchA, branch_b: branchB, steps, summary };
}

export class DiffError extends Error {}

function diffPoint(l: DecisionPoint, r: DecisionPoint): FieldDiff[] {
  const fields: FieldDiff[] = [];
  const la = l.input_context ?? {};
  const ra = r.input_context ?? {};
  walkDiff(la, ra, "input_context", fields);
  walkDiff(l.output ?? {}, r.output ?? {}, "output", fields);
  return fields;
}

function walkDiff(a: unknown, b: unknown, path: string, out: FieldDiff[]): void {
  if (JSON.stringify(a) === JSON.stringify(b)) return;
  if (a && b && typeof a === "object" && typeof b === "object") {
    const ao = a as Record<string, unknown>;
    const bo = b as Record<string, unknown>;
    const keys = new Set([...Object.keys(ao), ...Object.keys(bo)]);
    for (const k of keys) {
      walkDiff(ao[k], bo[k], `${path}.${k}`, out);
    }
    return;
  }
  out.push({ path, left: a ?? null, right: b ?? null, status: "changed" });
}

// ---- 采纳预览:把 diff 差异映射为对 branch_a 的 Fork 修改清单(只读) ----
export interface AdoptPreview {
  dry_run: true;
  branch_a: string;
  branch_b: string;
  modifications: { step: number; field: string; value: unknown }[];
}

export function previewAdopt(
  store: Store,
  branchA: string,
  branchB: string,
  fromStep: number,
  steps?: number[],
): AdoptPreview {
  const res = diffBranches(store, branchA, branchB);
  const modifications: AdoptPreview["modifications"] = [];
  for (const step of res.steps) {
    if (step.step_index < fromStep) continue;
    if (steps && !steps.includes(step.step_index)) continue;
    if (step.status !== "diff") continue;
    // 输入叶差异 → input_context.<路径>;输出差异 → output 整段覆盖(取右侧)
    const pointB = store
      .getDecisionPoints(store.getBranch(branchB)!.trace_id, branchB)
      .find((p) => p.step_index === step.step_index);
    for (const f of step.fields) {
      if (f.path.startsWith("input_context.")) {
        modifications.push({
          step: step.step_index,
          field: f.path,
          value: pickPath(pointB?.input_context ?? {}, f.path.slice("input_context.".length)),
        });
      }
    }
    if (pointB?.output) {
      modifications.push({ step: step.step_index, field: "output", value: pointB.output });
    }
  }
  return { dry_run: true, branch_a: branchA, branch_b: branchB, modifications };
}

function pickPath(obj: Record<string, unknown>, path: string): unknown {
  let cur: unknown = obj;
  for (const seg of path.split(".")) {
    if (cur && typeof cur === "object") cur = (cur as Record<string, unknown>)[seg];
    else return null;
  }
  return cur === undefined ? null : cur;
}
