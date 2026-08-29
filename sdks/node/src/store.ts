// 单文件 JSON store:内存操作同步,持久化经写队列串行原子落盘(tmp+rename)。
// 存储引擎是实现细节(行为契约与 Python 侧一致);已完成登记即入内存,落盘立即排程。
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { Branch, DecisionPoint, Lifecycle, Trace } from "./models.js";
import { newId, now } from "./models.js";

interface StoreData {
  traces: Trace[];
  branches: Branch[];
  points: DecisionPoint[];
}

export class Store {
  private data: StoreData;
  private saving: Promise<void> = Promise.resolve();
  private closed = false;

  constructor(readonly path: string) {
    if (existsSync(path)) {
      this.data = JSON.parse(readFileSync(path, "utf-8")) as StoreData;
    } else {
      this.data = { traces: [], branches: [], points: [] };
      const dir = dirname(path);
      if (dir && dir !== "." && !existsSync(dir)) mkdirSync(dir, { recursive: true });
      this.scheduleSave();
    }
  }

  // ---- 持久化:写队列串行,同一时刻至多一个在写的临时文件 ----
  private scheduleSave(): void {
    if (this.closed) return;
    this.saving = this.saving
      .then(() => this.writeNow())
      .catch((e) => {
        // 落盘失败不阻断内存操作(与 Python 侧"不因存储失败阻断执行"同哲学),但保留错误可见
        console.error("[agent-inspect] store save failed:", e);
      });
  }

  private writeNow(): void {
    const tmp = this.path + ".tmp";
    writeFileSync(tmp, JSON.stringify(this.data));
    renameSync(tmp, this.path);
  }

  async flush(): Promise<void> {
    await this.saving;
  }

  async close(): Promise<void> {
    await this.saving;
    this.closed = true;
  }

  // ---- traces ----
  createTraceWithRoot(agentName: string): { trace: Trace; branch: Branch } {
    const trace: Trace = {
      id: newId("tr"),
      started_at: now(),
      agent_name: agentName,
      root_branch_id: null,
      lifecycle: "running",
    };
    const branch: Branch = {
      id: newId("br"),
      trace_id: trace.id,
      parent_branch_id: null,
      branch_from_step: 0,
      origin: "record",
      note: null,
    };
    trace.root_branch_id = branch.id;
    this.data.branches.push(branch);
    this.data.traces.push(trace);
    this.scheduleSave();
    return { trace, branch };
  }

  listTraces(lifecycle?: Lifecycle): Trace[] {
    // 新者在先;同时钟平局按插入序(新者在先),与 Python 侧 rowid 次级键同语义
    const order = new Map(this.data.traces.map((t, i) => [t.id, i]));
    return this.data.traces
      .filter((t) => lifecycle === undefined || t.lifecycle === lifecycle)
      .sort(
        (a, b) =>
          b.started_at - a.started_at ||
          (order.get(b.id) as number) - (order.get(a.id) as number),
      )
      .map((t) => ({ ...t }));
  }

  getTrace(id: string): Trace | null {
    const t = this.data.traces.find((x) => x.id === id);
    return t ? { ...t } : null;
  }

  setTraceLifecycle(id: string, lifecycle: Lifecycle): void {
    const t = this.data.traces.find((x) => x.id === id);
    if (t) {
      t.lifecycle = lifecycle;
      this.scheduleSave();
    }
  }

  // ---- branches ----
  createBranch(
    traceId: string,
    parentBranchId: string,
    branchFromStep: number,
    origin: "fork",
    note: string | null,
  ): Branch {
    const branch: Branch = {
      id: newId("br"),
      trace_id: traceId,
      parent_branch_id: parentBranchId,
      branch_from_step: branchFromStep,
      origin,
      note,
    };
    this.data.branches.push(branch);
    this.scheduleSave();
    return { ...branch };
  }

  listBranches(traceId: string): Branch[] {
    return this.data.branches.filter((b) => b.trace_id === traceId).map((b) => ({ ...b }));
  }

  getBranch(id: string): Branch | null {
    const b = this.data.branches.find((x) => x.id === id);
    return b ? { ...b } : null;
  }

  // ---- decision points ----
  writeDecisionPoint(dp: DecisionPoint): void {
    this.data.points.push({ ...dp });
    this.scheduleSave();
  }

  getDecisionPoint(traceId: string, branchId: string, stepIndex: number): DecisionPoint | null {
    const p = this.data.points.find(
      (x) => x.trace_id === traceId && x.branch_id === branchId && x.step_index === stepIndex,
    );
    return p ? { ...p } : null;
  }

  getDecisionPoints(traceId: string, branchId: string, fromStep = 0, toStep?: number): DecisionPoint[] {
    return this.data.points
      .filter(
        (x) =>
          x.trace_id === traceId &&
          x.branch_id === branchId &&
          x.step_index >= fromStep &&
          (toStep === undefined || x.step_index <= toStep),
      )
      .sort((a, b) => a.step_index - b.step_index)
      .map((p) => ({ ...p }));
  }

  countDecisionPoints(traceId: string): number {
    return this.data.points.filter((x) => x.trace_id === traceId).length;
  }

  lastStepBefore(branchId: string, step: number): number | null {
    let best: number | null = null;
    for (const p of this.data.points) {
      if (p.branch_id === branchId && p.step_index < step) {
        if (best === null || p.step_index > best) best = p.step_index;
      }
    }
    return best;
  }
}
