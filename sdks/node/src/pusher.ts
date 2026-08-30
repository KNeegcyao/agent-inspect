// 推送链路到收集端点:与 Python pusher.py 同语义(载荷包装 + fetch + 可观测失败)。
import { exportTrace } from "./exporter.js";
import type { Store } from "./store.js";

export class PushError extends Error {}

export interface PushResult {
  delivered: number;
  statusCode: number;
  endpoint: string;
}

export async function pushTrace(
  store: Store,
  traceId: string,
  endpoint: string,
  timeoutMs = 10000,
): Promise<PushResult> {
  const trace = store.getTrace(traceId);
  if (!trace) throw new PushError(`trace ${traceId} not found`);
  const envelope = exportTrace(store, traceId);
  const payload = wrapPayload(envelope);
  const body = JSON.stringify(payload);

  let statusCode: number;
  try {
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: AbortSignal.timeout(timeoutMs),
    });
    statusCode = resp.status;
  } catch (e) {
    throw new PushError(`endpoint unreachable: ${String((e as Error)?.message ?? e)}`);
  }
  if (statusCode < 200 || statusCode >= 300) {
    throw new PushError(`endpoint responded ${statusCode}`);
  }
  const delivered = spansOf(payload).length;
  return { delivered, statusCode, endpoint };
}

function spansOf(payload: Record<string, any>): any[] {
  const out: any[] = [];
  for (const rs of payload.resourceSpans ?? []) {
    for (const ss of rs.scopeSpans ?? []) out.push(...(ss.spans ?? []));
  }
  return out;
}

// 导出信封 → 推送载荷:补 scope 声明与 span kind(LLM=CLIENT 3 / TOOL=INTERNAL 1)
function wrapPayload(envelope: Record<string, any>): Record<string, any> {
  const resourceSpans = (envelope.resourceSpans ?? []).map((rs: any) => ({
    ...rs,
    scopeSpans: (rs.scopeSpans ?? []).map((ss: any) => ({
      ...ss,
      scope: { name: "agent-inspect" },
      spans: (ss.spans ?? []).map((span: any) => {
        const kindAttr = (span.attributes ?? []).find((a: any) => a.key === "openinference.span.kind");
        const isLlm = kindAttr?.value?.stringValue === "LLM";
        return { ...span, kind: isLlm ? 3 : 1 };
      }),
    })),
  }));
  return { resourceSpans: resourceSpans };
}
