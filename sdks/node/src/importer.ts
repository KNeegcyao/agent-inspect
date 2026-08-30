// 外部 span 导出导入:与 Python importer.py 同语义(两形态、映射、拒绝不落库)。
import type { DecisionPoint } from "./models.js";
import { newId, now } from "./models.js";
import type { Store } from "./store.js";

export const KIND_ATTR = "openinference.span.kind";
export const SPAN_KIND_LLM = "LLM";
export const SPAN_KIND_TOOL = "TOOL";

export class TraceImportError extends Error {}

export interface ImportResult {
  traceId: string;
  rootBranchId: string;
  decisionPoints: number;
  skipped: number;
}

// ---------------------------------------------------------------------------
// 输入形态:OTLP 信封 / 扁平列表
// ---------------------------------------------------------------------------
function extractSpans(payload: unknown): { spans: Record<string, unknown>[]; agentName: string } {
  if (!payload || typeof payload !== "object") {
    throw new TraceImportError("export must be a JSON object");
  }
  const p = payload as Record<string, any>;
  let agentName = "imported";
  let spans: Record<string, unknown>[] = [];

  if (Array.isArray(p.resourceSpans)) {
    for (const res of p.resourceSpans) {
      if (!res || typeof res !== "object") continue;
      const resAttrs = res.resource?.attributes;
      const svc = (Array.isArray(resAttrs) ? flatAttrs(resAttrs) : resAttrs ?? {})["service.name"];
      if (svc) agentName = String(svc);
      for (const scope of res.scopeSpans ?? []) {
        if (scope && typeof scope === "object") {
          spans.push(...((scope.spans ?? []) as any[]).filter((s) => s && typeof s === "object"));
        }
      }
    }
  } else if (Array.isArray(p.spans)) {
    spans = p.spans.filter((s) => s && typeof s === "object");
    agentName = p.agent_name || p["service.name"] || agentName;
  }
  if (!spans.length) {
    throw new TraceImportError(
      "no spans found in export (need resourceSpans[].scopeSpans[].spans[] or spans[])",
    );
  }
  return { spans, agentName: String(agentName) };
}

// ---------------------------------------------------------------------------
// span 字段读取(OTLP camelCase / 扁平 snake_case 兼容)
// ---------------------------------------------------------------------------
function flatAttrs(values: unknown[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const a of values) {
    const a2 = a as { key?: string; value?: unknown };
    if (a2 && a2.key) out[a2.key] = otlpValue(a2.value);
  }
  return out;
}

function attrMap(span: Record<string, any>): Record<string, unknown> {
  const attrs = span.attributes;
  if (Array.isArray(attrs)) {
    const out: Record<string, unknown> = {};
    for (const a of attrs) {
      if (a && a.key) out[a.key] = otlpValue(a.value);
    }
    return out;
  }
  return attrs && typeof attrs === "object" ? attrs : {};
}

function otlpValue(v: any): unknown {
  if (!v || typeof v !== "object") return v;
  for (const k of ["stringValue", "intValue", "doubleValue", "boolValue"]) {
    if (k in v) return v[k];
  }
  if (v.arrayValue && typeof v.arrayValue === "object") {
    return (v.arrayValue.values ?? []).map(otlpValue);
  }
  if (v.kvlistValue && typeof v.kvlistValue === "object") {
    return flatAttrs(v.kvlistValue.values ?? []);
  }
  return v;
}

function spanId(span: Record<string, any>): string {
  return String(span.spanId ?? span.span_id ?? "");
}

function parentId(span: Record<string, any>): string {
  return String(span.parentSpanId ?? span.parent_span_id ?? "");
}

function rawStart(span: Record<string, any>): number {
  const v = span.startTimeUnixNano ?? span.start_time;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function unitDivisor(n: number): number {
  if (n >= 1e17) return 1e9; // ns
  if (n >= 1e14) return 1e6; // µs
  if (n >= 1e11) return 1e3; // ms
  return 1;
}

function startSec(span: Record<string, any>): number {
  return rawStart(span) / unitDivisor(rawStart(span));
}

function durationMs(span: Record<string, any>): number | null {
  const endV = span.endTimeUnixNano ?? span.end_time;
  const end = Number(endV);
  const start = rawStart(span);
  if (!Number.isFinite(end) || start <= 0 || end <= start) return null;
  return Math.round(((end - start) / unitDivisor(start)) * 1000 * 10) / 10;
}

function spanKind(span: Record<string, any>): string | null {
  const k = attrMap(span)[KIND_ATTR];
  return typeof k === "string" ? k : null;
}

// ---------------------------------------------------------------------------
// 排序:父 span 建树 + DFS(稳序 start/spanId);孤儿/环兜底
// ---------------------------------------------------------------------------
function orderSpans(spans: Record<string, any>[]): Record<string, any>[] {
  const byId = new Map<string, Record<string, any>>();
  for (const s of spans) {
    const id = spanId(s);
    if (id) byId.set(id, s);
  }
  const children = new Map<string, Record<string, any>[]>();
  const roots: Record<string, any>[] = [];
  for (const s of spans) {
    const pid = parentId(s);
    const sid = spanId(s);
    if (pid && byId.has(pid) && pid !== sid) {
      if (!children.has(pid)) children.set(pid, []);
      children.get(pid)!.push(s);
    } else {
      roots.push(s);
    }
  }
  const key = (s: Record<string, any>) => [rawStart(s), spanId(s)] as const;
  roots.sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    return ka[0] - kb[0] || (ka[1] < kb[1] ? -1 : 1);
  });
  for (const list of children.values()) {
    list.sort((a, b) => {
      const ka = key(a);
      const kb = key(b);
      return ka[0] - kb[0] || (ka[1] < kb[1] ? -1 : 1);
    });
  }
  const out: Record<string, any>[] = [];
  const seen = new Set<object>();
  const visit = (s: Record<string, any>) => {
    if (seen.has(s)) return;
    seen.add(s);
    out.push(s);
    for (const c of children.get(spanId(s)) ?? []) visit(c);
  };
  for (const r of roots) visit(r);
  for (const s of [...spans].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    return ka[0] - kb[0] || (ka[1] < kb[1] ? -1 : 1);
  })) {
    visit(s);
  }
  return out;
}

// ---------------------------------------------------------------------------
// 映射:span → 决策点(与 Node 插桩器 shape 同形)
// ---------------------------------------------------------------------------
function jsonAny(v: unknown): unknown {
  if (typeof v === "string") {
    try {
      return JSON.parse(v);
    } catch {
      return v;
    }
  }
  return v;
}

function jsonDict(v: unknown): Record<string, unknown> {
  const d = jsonAny(v);
  return d && typeof d === "object" && !Array.isArray(d) ? (d as Record<string, unknown>) : {};
}

function jsonList(v: unknown): unknown[] {
  const d = jsonAny(v);
  return Array.isArray(d) ? d : [];
}

function msgField(msg: unknown, field: string): unknown {
  if (msg && typeof msg === "object") {
    const inner = (msg as any).message;
    if (inner && typeof inner === "object") return inner[field];
    return (msg as any)[field] ?? (msg as any)[`message.${field}`];
  }
  return null;
}

function msgRecord(msg: unknown): Record<string, unknown> {
  const rec: Record<string, unknown> = {
    role: msgField(msg, "role") ?? null,
    content: msgField(msg, "content") ?? null,
  };
  const tc = msgField(msg, "tool_calls");
  if (tc) rec["tool_calls"] = tc;
  return rec;
}

function messagesFrom(attrs: Record<string, unknown>, prefix: string): Record<string, unknown>[] {
  const raw = jsonList(attrs[prefix]);
  if (raw.length) return raw.map(msgRecord);
  const perIdx = new Map<number, Record<string, unknown>>();
  for (const [k, v] of Object.entries(attrs)) {
    if (!k.startsWith(prefix + ".")) continue;
    const parts = k.slice(prefix.length + 1).split(".");
    if (!parts[0] || !/^\d+$/.test(parts[0])) continue;
    const idxKey = Number(parts[0]);
    const slot = perIdx.get(idxKey) ?? {};
    perIdx.set(idxKey, slot);
    slot[parts.slice(1).join(".")] = v;
  }
  const out: Record<string, unknown>[] = [];
  for (const i of [...perIdx.keys()].sort((a, b) => a - b)) {
    const slot = perIdx.get(i)!;
    const rec: Record<string, unknown> = {
      role: slot["message.role"] ?? "user",
      content: slot["message.content"] ?? null,
    };
    if (slot["message.tool_calls"]) rec["tool_calls"] = slot["message.tool_calls"];
    out.push(rec);
  }
  return out;
}

function dpFromSpan(
  traceId: string,
  branchId: string,
  step: number,
  span: Record<string, any>,
  prevDpId: string | null,
): DecisionPoint {
  const kindAttr = spanKind(span);
  const attrs = attrMap(span);
  const name = (span.name as string) || "span";
  let dpKind: "llm" | "tool";
  let agentId: string;
  let inputContext: Record<string, unknown>;
  let output: Record<string, unknown>;

  if (kindAttr === SPAN_KIND_LLM) {
    dpKind = "llm";
    agentId = name;
        inputContext = {
      messages: messagesFrom(attrs, "llm.input_messages"),
      model: attrs["llm.model_name"] || attrs["llm.model"] || null,
      params: jsonDict(attrs["llm.invocation_parameters"]),
    } as Record<string, unknown>;
    const outMsgs = messagesFrom(attrs, "llm.output_messages");
    let content: unknown = null;
    let toolCalls: unknown[] = [];
    for (const m of outMsgs) {
      if ((m["role"] ?? "assistant") === "assistant") {
        content = m["content"];
        toolCalls = Array.isArray(m["tool_calls"]) ? (m["tool_calls"] as unknown[]) : [];
        break;
      }
    }
    if (content === null && outMsgs.length) content = outMsgs[outMsgs.length - 1]["content"];
    if (!toolCalls.length) toolCalls = jsonList(attrs["llm.tool_calls"]);
    output = { content, tool_calls: tool_calls_ensure(toolCalls) };
  } else {
    dpKind = "tool";
    agentId = String(attrs["tool.name"] ?? name);
    inputContext = {
      tool: attrs["tool.name"] ?? name,
      args: jsonAny(attrs["tool.parameters"]),
    };
    output = {
      result: jsonAny(attrs["tool.return_value"]),
      is_error: Boolean(attrs["tool.is_error"]),
    };
  }

  const meta: Record<string, unknown> = { imported: true };
  const sid = spanId(span);
  if (sid) meta["imported_span_id"] = sid;
  const lat = durationMs(span);
  if (lat !== null) meta["latency_ms"] = lat;

  return {
    id: newId("dp"),
    trace_id: traceId,
    branch_id: branchId,
    step_index: step,
    kind: dpKind,
    agent_id: agentId,
    input_context: inputContext,
    output,
    output_hash: null,
    cause_edge: prevDpId ? [prevDpId] : [],
    meta,
  };
}

function tool_calls_ensure(tc: unknown): unknown[] {
  return Array.isArray(tc) ? tc : [];
}

// ---------------------------------------------------------------------------
// 入口
// ---------------------------------------------------------------------------
export function importTrace(store: Store, payload: unknown): ImportResult {
  const { spans, agentName } = extractSpans(payload);
  const ordered = orderSpans(spans);
  const mapped = ordered.filter((s) => [SPAN_KIND_LLM, SPAN_KIND_TOOL].includes(spanKind(s) ?? ""));
  const skipped = ordered.length - mapped.length;
  if (!mapped.length) {
    throw new TraceImportError(
      `no importable spans found: need spans with ${KIND_ATTR} in (${SPAN_KIND_LLM}, ${SPAN_KIND_TOOL})`,
    );
  }

  const starts = ordered.map(startSec).filter((s) => s > 0);
  const startedAt = starts.length ? Math.min(...starts) : now();

  const { trace, branch } = store.createTraceWithRoot(agentName);
  store.setTraceLifecycle(trace.id, "done");
  store.setTraceStartedAt(trace.id, startedAt);

  let prevDpId: string | null = null;
  let count = 0;
  for (const span of mapped) {
    const dp = dpFromSpan(trace.id, branch.id, count, span, prevDpId);
    store.writeDecisionPoint(dp);
    prevDpId = dp.id;
    count += 1;
  }
  return {
    traceId: trace.id,
    rootBranchId: branch.id,
    decisionPoints: count,
    skipped,
  };
}
