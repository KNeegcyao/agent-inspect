// 内嵌 HTTP 服务:REST 子集 + SSE + 静态面板(node:http,零依赖)。
import { createServer, IncomingMessage, Server, ServerResponse } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { join, extname } from "node:path";
import { ForkError, type Modification } from "./fork.js";
import { diffBranches, DiffError, previewAdopt } from "./diff.js";
import { TraceExportError, exportTrace } from "./exporter.js";
import { TraceImportError, importTrace } from "./importer.js";
import { PushError, pushTrace } from "./pusher.js";
import type { Session } from "./session.js";

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

const PLACEHOLDER = `<!doctype html><html><head><meta charset="utf-8"><title>Agent-Inspect</title></head>
<body style="font-family:monospace;background:#0f1420;color:#dbe4ff"><h2>Agent-Inspect</h2>
<p>面板构建产物缺失(panel/),REST 契约仍可用:/api/traces</p></body></html>`;

export function createHttpServer(session: Session): Server {
  const server = createServer((req, res) => {
    void handle(session, req, res).catch((e) => {
      if (e instanceof ApiError) json(res, 422, { error: e.message });
      else json(res, 500, { error: String((e as Error)?.message ?? e) });
    });
  });
  return server;
}

async function handle(session: Session, req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", "http://localhost");
  const path = url.pathname;
  const method = req.method ?? "GET";

  if (method === "GET" && path === "/api/events") return sse(session, req, res);

  if (path.startsWith("/api/")) {
    try {
      await apiRoute(session, method, path, url, req, res);
    } catch (e) {
      if (e instanceof ForkError || e instanceof DiffError) json(res, 422, { error: e.message });
      else if (e instanceof TraceExportError) json(res, 404, { error: e.message });
      else throw e;
    }
    return;
  }

  if (method === "GET") return staticPanel(session, path, res);
  json(res, 404, { error: "not found" });
}

async function apiRoute(
  session: Session,
  method: string,
  path: string,
  url: URL,
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const { store } = session;
  const seg = path.split("/").filter(Boolean); // ["api", ...]

  // GET /api/traces
  if (method === "GET" && path === "/api/traces") {
    const lc = url.searchParams.get("lifecycle");
    return json(res, 200, store.listTraces((lc as "running" | "done" | "aborted") || undefined));
  }

  // POST /api/forks
  if (method === "POST" && path === "/api/forks") {
    const body = await readJson(req);
    const t = store.getTrace(String(body["trace_id"] ?? ""));
    if (!t) return json(res, 404, { error: "trace not found" });
    const { branch, plan } = await session.fork.requestFork({
      traceId: String(body["trace_id"]),
      fromBranch: String(body["branch_id"] ?? ""),
      fromStep: Number(body["from_step"] ?? 0),
      modifications: (body["modifications"] as Modification[] | undefined) ?? [],
      dryRun: Boolean(body["dry_run"]),
      note: (body["note"] as string | undefined) ?? null,
      sandbox: (body["sandbox"] as Record<string, string> | undefined) ?? null,
    });
    return json(res, 200, { branch, plan });
  }

  // /api/debug/*(Mode C live 调试,与 Python 同契约)
  if (seg[1] === "debug") {
    const traceId = seg[2];
    const t = traceId ? store.getTrace(traceId) : null;
    const gate = session.debug.gate(traceId) ?? session.debug.ensureGate(traceId);
    if (seg[3] === "attach" && method === "POST") {
      if (!t) return json(res, 404, { error: "trace not found" });
      if (t.lifecycle !== "running") {
        return json(res, 422, { error: `trace not running (lifecycle=${t.lifecycle})` });
      }
      const first = gate.attach();
      return json(res, 200, { ...(gate.state() as Record<string, unknown>), first });
    }
    if (seg[3] === "state" && method === "GET") {
      return json(res, 200, gate.state());
    }
    if (seg[3] === "breakpoints") {
      if (method === "GET") return json(res, 200, store.listBreakpoints(traceId));
      if (method === "POST") {
        const body = await readJson(req);
        const bp = gate.addBreakpoint({
          kind: (body["kind"] as string | undefined) ?? null,
          agentId: (body["agent_id"] as string | undefined) ?? null,
          condition: (body["condition"] as string | undefined) ?? null,
        });
        return json(res, 200, { ...bp });
      }
      if (method === "DELETE" && seg[4]) {
        const ok = gate.removeBreakpoint(seg[4]);
        return ok
          ? json(res, 200, { ok: true, breakpoint_id: seg[4] })
          : json(res, 404, { error: "breakpoint not found" });
      }
    }
    if (seg[3] === "pause" && method === "POST") {
      gate.pause();
      return json(res, 200, { ok: true, action: "pause" });
    }
    if (seg[3] === "step" && method === "POST") {
      const body = await readJson(req);
      const released = gate.step((body["at_step"] as number | undefined) ?? null);
      return json(res, 200, { ok: true, action: "step", released });
    }
    if (seg[3] === "continue" && method === "POST") {
      const body = await readJson(req);
      const released = gate.resume((body["at_step"] as number | undefined) ?? null);
      return json(res, 200, { ok: true, action: "continue", released });
    }
    if (seg[3] === "modify" && method === "POST") {
      const body = await readJson(req);
      if (!("step" in body) || !("field" in body) || !("value" in body)) {
        return json(res, 422, { error: "step/field/value required" });
      }
      gate.modify(Number(body["step"]), String(body["field"]), body["value"]);
      return json(res, 200, { ok: true, action: "modify", step: Number(body["step"]) });
    }
    return json(res, 404, { error: "not found" });
  }

  // POST /api/traces/import(外部 span 导出导入)
  if (method === "POST" && path === "/api/traces/import") {
    const bodyText = await readRaw(req);
    let parsed: unknown;
    try {
      parsed = JSON.parse(bodyText);
    } catch {
      return json(res, 422, { error: "request body is not valid JSON" });
    }
    try {
      const r = importTrace(store, parsed);
      session.emit("trace.imported", {
        trace_id: r.traceId,
        decision_points: r.decisionPoints,
        skipped: r.skipped,
      });
      return json(res, 200, {
        trace_id: r.traceId,
        root_branch_id: r.rootBranchId,
        decision_points: r.decisionPoints,
        skipped: r.skipped,
      });
    } catch (e) {
      if (e instanceof TraceImportError) return json(res, 422, { error: e.message });
      throw e;
    }
  }

  // /api/traces/*
  if (seg[1] === "traces") {
    if (!seg[2]) return notFound(res);
    const traceId = seg[2];
    if (seg.length === 3 && method === "GET") {
      const t = store.getTrace(traceId);
      if (!t) return json(res, 404, { error: "trace not found" });
      return json(res, 200, { trace: t, branches: store.listBranches(traceId), children: [] });
    }
    if (seg.length === 4 && seg[3] === "export" && method === "GET") {
      const envelope = exportTrace(store, traceId);
      const t = store.getTrace(traceId)!;
      const filename = `${t.agent_name || "trace"}-${traceId.slice(-8)}.json`;
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Content-Disposition": `attachment; filename="${filename}"`,
      });
      res.end(JSON.stringify(envelope));
      return;
    }
    if (seg.length === 4 && seg[3] === "push" && method === "POST") {
      if (!t0(session, traceId)) return json(res, 404, { error: "trace not found" });
      const body = await readJson(req);
      const endpoint = body["endpoint"];
      if (!endpoint || !String(endpoint).startsWith("http")) {
        return json(res, 422, { error: "endpoint must be an http(s) URL" });
      }
      const timeoutMs = Number(body["timeoutMs"] ?? 10000) || 10000;
      try {
        const r = await pushTrace(store, traceId, String(endpoint), timeoutMs);
        return json(res, 200, { delivered: r.delivered, endpoint: r.endpoint, status_code: r.statusCode });
      } catch (e) {
        if (e instanceof PushError) return json(res, 502, { error: e.message });
        throw e;
      }
    }
    if (seg.length === 4 && seg[3] === "lifecycle" && method === "POST") {
      const body = await readJson(req);
      const lc = body["lifecycle"];
      if (lc !== "running" && lc !== "done" && lc !== "aborted") {
        return json(res, 422, { error: `invalid lifecycle: ${lc}` });
      }
      if (!store.getTrace(traceId)) return json(res, 404, { error: "trace not found" });
      store.setTraceLifecycle(traceId, lc);
      return json(res, 200, { ok: true, trace_id: traceId, lifecycle: lc });
    }
    return notFound(res);
  }

  // /api/branches/*
  if (seg[1] === "branches") {
    // GET /api/branches(全局分支索引)
    if (seg.length === 2 && method === "GET") {
      const out = [];
      for (const t of store.listTraces()) {
        for (const b of store.listBranches(t.id)) {
          out.push({
            ...b,
            trace_id: t.id,
            trace_name: t.agent_name || t.id,
            trace_lifecycle: t.lifecycle,
          });
        }
      }
      return json(res, 200, out);
    }
    const branchId = seg[2];
    const branch = store.getBranch(branchId ?? "");
    if (!branch) return json(res, 404, { error: "branch not found" });
    if (method === "GET" && seg[3] === "points" && seg.length === 4) {
      return json(res, 200, store.getDecisionPoints(branch.trace_id, branchId));
    }
    if (method === "GET" && seg[3] === "diff" && seg[4] && seg.length === 5) {
      const other = store.getBranch(seg[4]);
      if (!other) return json(res, 404, { error: "branch not found" });
      const result = diffBranches(store, branchId, seg[4]);
      const ta = store.getTrace(branch.trace_id);
      const tb = store.getTrace(other.trace_id);
      return json(res, 200, {
        ...result,
        trace_a: ta?.agent_name ?? branch.trace_id,
        trace_b: tb?.agent_name ?? other.trace_id,
      });
    }
    if (method === "POST" && seg[3] === "diff" && seg[4] && seg[5] === "adopt" && seg.length === 6) {
      const body = await readJson(req);
      const fromStep = Number(body["from_step"] ?? 0);
      if (Number.isNaN(fromStep)) return json(res, 422, { error: "from_step must be an int" });
      if (store.countDecisionPoints(branch.trace_id) === 0) {
        return json(res, 422, { error: "cannot adopt onto empty trace" });
      }
      const steps = body["steps"] as number[] | undefined;
      return json(res, 200, previewAdopt(store, branchId, seg[4], fromStep, steps));
    }
    return notFound(res);
  }

  notFound(res);
}

function notFound(res: ServerResponse): void {
  json(res, 404, { error: "not found" });
}

async function readRaw(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf-8");
}

function t0(session: Session, traceId: string): boolean {
  return !!session.store.getTrace(traceId);
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const raw = Buffer.concat(chunks).toString("utf-8");
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    throw new ApiError("request body is not valid JSON");
  }
}

export class ApiError extends Error {}

function json(res: ServerResponse, status: number, payload: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(payload));
}

// ---- SSE ----
function sse(session: Session, req: IncomingMessage, res: ServerResponse): void {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  res.write(":connected\n\n");
  const queue: string[] = [];
  const send = (frame: string) => {
    queue.push(frame);
    if (queue.length === 1) drain();
  };
  const drain = () => {
    while (queue.length) {
      const frame = queue.shift()!;
      res.write(frame);
    }
  };
  session.events.add(send);
  req.on("close", () => session.events.delete(send));
}

// ---- 静态面板 ----
function staticPanel(session: Session, path: string, res: ServerResponse): void {
  const rel = path === "/" ? "index.html" : path.slice(1);
  const root = session.panelDir;
  if (root) {
    const file = join(root, rel);
    if (file.startsWith(root) && existsSync(file)) {
      const type = MIME[extname(file)] ?? "application/octet-stream";
      res.writeHead(200, { "Content-Type": type });
      res.end(readFileSync(file));
      return;
    }
    // SPA 兜底:非资源路径回 index.html
    const index = join(root, "index.html");
    if (!extname(rel) && existsSync(index)) {
      res.writeHead(200, { "Content-Type": MIME[".html"] });
      res.end(readFileSync(index));
      return;
    }
  }
  res.writeHead(200, { "Content-Type": MIME[".html"] });
  res.end(PLACEHOLDER);
}
