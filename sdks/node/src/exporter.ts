// 链路导出:trace 决策链 → span 导出 JSON(与 Python exporter 同契约,只读)。
import type { Store } from "./store.js";

export class TraceExportError extends Error {}

export function exportTrace(
  store: Store,
  traceId: string,
  branchId?: string,
): Record<string, unknown> {
  const trace = store.getTrace(traceId);
  if (!trace) throw new TraceExportError(`trace ${traceId} not found`);
  const bid = branchId ?? trace.root_branch_id;
  const branch = bid ? store.getBranch(bid) : null;
  if (!branch || branch.trace_id !== traceId) {
    throw new TraceExportError(`branch ${bid ?? "?"} not found in trace ${traceId}`);
  }
  const points = store.getDecisionPoints(traceId, branch.id);
  const baseNs = Math.round(trace.started_at * 1e9);
  const traceIdHex = trace.id.replace(/^tr_/, "").padEnd(32, "0").slice(0, 32);

  const spans: Record<string, unknown>[] = [];
  let prevSpanId = "";
  points.forEach((p, i) => {
    const spanId = (i + 1).toString(16).padStart(16, "0");
    const startNs = baseNs + i * 1_000_000;
    const latency = Number(p.meta?.["latency_ms"] ?? 1) || 1;
    const endNs = startNs + Math.round(latency * 1e6);
    spans.push({
      traceId: traceIdHex,
      spanId,
      parentSpanId: prevSpanId,
      name: p.agent_id,
      startTimeUnixNano: String(startNs),
      endTimeUnixNano: String(endNs),
      attributes: spanAttrs(p),
    });
    prevSpanId = spanId;
  });

  return {
    resourceSpans: [
      {
        resource: {
          attributes: [
            { key: "service.name", value: { stringValue: trace.agent_name || "agent" } },
          ],
        },
        scopeSpans: [{ spans }],
      },
    ],
  };
}

type Point = {
  kind: string;
  agent_id: string;
  input_context: Record<string, unknown>;
  output: Record<string, unknown> | null;
  meta: Record<string, unknown>;
};

function spanAttrs(p: Point): unknown[] {
  const j = (v: unknown) => JSON.stringify(v ?? null);
  if (p.kind === "llm") {
    const inp = p.input_context;
    const out = p.output ?? {};
    const inputMessages = (inp["messages"] as unknown[] | undefined)?.map((m) => ({
      message: m,
    }));
    const outMsgs = [
      {
        message: {
          role: "assistant",
          content: out["content"] ?? null,
          ...(out["tool_calls"] ? { tool_calls: out["tool_calls"] } : {}),
        },
      },
    ];
    const attrs: unknown[] = [
      { key: "openinference.span.kind", value: { stringValue: "LLM" } },
      { key: "llm.model_name", value: { stringValue: String(inp["model"] ?? "") } },
      { key: "llm.input_messages", value: { stringValue: j(inputMessages ?? []) } },
      { key: "llm.output_messages", value: { stringValue: j(outMsgs) } },
    ];
    if (inp["params"] && Object.keys(inp["params"] as object).length) {
      attrs.push({
        key: "llm.invocation_parameters",
        value: { stringValue: j(inp["params"]) },
      });
    }
    return attrs;
  }
  const inp = p.input_context;
  const out = p.output ?? {};
  const attrs: unknown[] = [
    { key: "openinference.span.kind", value: { stringValue: "TOOL" } },
    { key: "tool.name", value: { stringValue: String(inp["tool"] ?? p.agent_id) } },
    { key: "tool.parameters", value: { stringValue: j(inp["args"]) } },
    { key: "tool.return_value", value: { stringValue: j(out["result"]) } },
  ];
  if (out["is_error"]) attrs.push({ key: "tool.is_error", value: { boolValue: true } });
  return attrs;
}
