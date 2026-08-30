// Session:一行启用装配 store / interceptor / fork / server / 插桩。
import * as net from "node:net";
import { exec } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Store } from "./store.js";
import { ForkController } from "./fork.js";
import { Interceptor } from "./interceptor.js";
import { createHttpServer } from "./server.js";
import { installOpenAIInterceptor, type Patcher } from "./patchers/openai.js";
import { DebugController } from "./debug.js";
import { enterCursor, type Cursor } from "./context.js";

export interface StartOptions {
  dbPath?: string;
  port?: number;
  uiDir?: string;
  autostartBrowser?: boolean;
  agentName?: string;
}

export interface StartResult extends Session {}

export class Session {
  store: Store;
  fork: ForkController;
  debug: DebugController;
  interceptor: Interceptor;
  url = "";
  port = 0;
  panelDir: string | null;
  events = new Set<(frame: string) => void>();

  private server: ReturnType<typeof createHttpServer>;
  private patcher: Patcher | null = null;
  private currentCursor: Cursor | null = null;
  // listen 是异步的:port/url 在 ready 后才有效
  readonly ready: Promise<number>;

  constructor(opts: StartOptions = {}) {
    const dbPath =
      opts.dbPath ??
      join(process.env.HOME ?? process.env.USERPROFILE ?? ".", ".agent-inspect", "agent-inspect-node.json");
    this.store = new Store(dbPath);
    this.fork = new ForkController(this.store);
    this.debug = new DebugController(this.store, (event, payload) => this.emit(event, payload));
    this.interceptor = new Interceptor(
      this.store,
      this.fork,
      (event, payload) => {
        const frame = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
        for (const send of this.events) send(frame);
      },
      this.debug,
    );
    this.panelDir = opts.uiDir ?? defaultPanelDir();
    this.server = createHttpServer(this);
    const preferred = opts.port ?? 8765;
    this.ready = new Promise((resolve, reject) => {
      this.server.once("listening", () => {
        this.port = (this.server.address() as { port: number }).port;
        this.url = `http://127.0.0.1:${this.port}`;
        resolve(this.port);
      });
      this.server.once("error", reject);
      // 端口探测本身是异步的:先探测可用端口再 listen(EADDRINUSE 自动让位)
      if (preferred === 0) {
        this.server.listen(0, "127.0.0.1");
      } else {
        void pickPort(preferred).then(
          (p) => this.server.listen(p, "127.0.0.1"),
          reject,
        );
      }
    });
    void this.patcherPromise();
  }

  /** 异步工厂:等待端口就绪,再开浏览器(保证 url/port 可用) */
  static async create(opts: StartOptions = {}): Promise<Session> {
    const s = new Session(opts);
    await s.ready;
    if (opts.autostartBrowser !== false) openBrowser(s.url);
    return s;
  }

  private async patcherPromise(): Promise<void> {
    this.patcher = await installOpenAIInterceptor(this.interceptor);
  }

  // 把一段 Agent 执行括进一个 trace 生命周期(对应 Python session.trace)
  async trace<T>(fn: () => Promise<T>): Promise<string> {
    const { cursor, traceId } = this.interceptor.acquireContext();
    this.currentCursor = cursor;
    try {
      await fn();
      this.store.setTraceLifecycle(traceId, "done");
      this.emit("trace.done", { trace_id: traceId });
      return traceId;
    } catch (e) {
      this.store.setTraceLifecycle(traceId, "aborted");
      this.emit("trace.aborted", { trace_id: traceId });
      throw e;
    } finally {
      this.currentCursor = null;
      enterCursor(null); // 退出即清游标:后续执行不再误入已完成 trace(对应 Python reset_cursor)
    }
  }

  emit(event: string, payload: unknown): void {
    const frame = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
    for (const send of this.events) send(frame);
  }

  async stop(): Promise<void> {
    this.patcher?.restore();
    this.patcher = null;
    await this.store.flush();
    // SSE 长连接会阻塞 close 回调:先强制断开所有连接再等关闭
    (this.server as unknown as { closeAllConnections?: () => void }).closeAllConnections?.();
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
    await this.store.close();
  }
}

export async function start(opts: StartOptions = {}): Promise<Session> {
  return Session.create(opts);
}

function pickPort(preferred: number): Promise<number> {
  const tryPort = (p: number): Promise<number> =>
    new Promise((resolve) => {
      if (p >= preferred + 50) return resolve(preferred);
      const probe = net.createServer();
      probe.once("listening", () => probe.close(() => resolve(p)));
      probe.once("error", () => probe.close(() => void resolve(tryPort(p + 1))));
      probe.listen(p, "127.0.0.1");
    });
  return tryPort(preferred);
}

function defaultPanelDir(): string | null {
  // npm 包内:dist/../panel;仓库开发态:../../web/dist
  const here = fileURLToPath(new URL(".", import.meta.url));
  const candidates = [
    join(here, "..", "..", "panel"),
    join(here, "..", "..", "..", "..", "web", "dist"),
  ];
  for (const c of candidates) {
    if (existsSync(join(c, "index.html"))) return c;
  }
  return null;
}

function openBrowser(url: string): void {
  const cmd =
    process.platform === "win32"
      ? `start "" "${url}"`
      : process.platform === "darwin"
        ? `open "${url}"`
        : `xdg-open "${url}"`;
  try {
    exec(cmd);
  } catch {
    /* 无头环境:仅打印 URL */
  }
}
