// 决策点 / 分支 / trace 数据模型(内部实现,不进 spec)。
import { createHash, randomUUID } from "node:crypto";

export type Lifecycle = "running" | "done" | "aborted";
export type Kind = "llm" | "tool";
export type Origin = "record" | "fork";

export interface Trace {
  id: string;
  started_at: number;
  agent_name: string;
  root_branch_id: string | null;
  lifecycle: Lifecycle;
}

export interface Branch {
  id: string;
  trace_id: string;
  parent_branch_id: string | null;
  branch_from_step: number;
  origin: Origin;
  note: string | null;
}

export interface DecisionPoint {
  id: string;
  trace_id: string;
  branch_id: string;
  step_index: number;
  kind: Kind;
  agent_id: string;
  input_context: Record<string, unknown>;
  output: Record<string, unknown> | null;
  output_hash: string | null;
  cause_edge: string[];
  meta: Record<string, unknown>;
}

let seq = 0;

export function newId(prefix: string): string {
  seq = (seq + 1) % 0xffff;
  const rand = randomUUID().replace(/-/g, "").slice(0, 12);
  return `${prefix}_${rand}${seq.toString(16).padStart(4, "0")}`;
}

export function now(): number {
  return Date.now() / 1000;
}

// 稳定序列化(键排序),与 Python 侧 json.dumps(sort_keys=True) 同语义,保证 output_hash 可比
export function stableStringify(value: unknown): string {
  return JSON.stringify(sortKeysDeep(value));
}

function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value as Record<string, unknown>).sort()) {
      out[k] = sortKeysDeep((value as Record<string, unknown>)[k]);
    }
    return out;
  }
  return value;
}

export function hashOf(obj: unknown): string {
  return "sha256:" + createHash("sha256").update(stableStringify(obj)).digest("hex");
}
