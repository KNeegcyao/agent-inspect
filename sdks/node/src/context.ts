// 执行模式上下文:AsyncLocalStorage 贯穿 async(对应 Python 侧 contextvars)。
import { AsyncLocalStorage } from "node:async_hooks";

export const MODE_RECORD = "record";
export const MODE_REPLAY = "replay";
export const MODE_FORK = "fork";

export class Cursor {
  traceId: string;
  branchId: string;
  mode: string;
  replayBranchId: string | null;
  branchFromStep: number;
  dryRun: boolean;
  stepIndex = -1;
  lastDpId: string | null = null;
  liveDebug = false;

  constructor(opts: {
    traceId: string;
    branchId: string;
    mode?: string;
    replayBranchId?: string | null;
    branchFromStep?: number;
    dryRun?: boolean;
    liveDebug?: boolean;
  }) {
    this.traceId = opts.traceId;
    this.branchId = opts.branchId;
    this.mode = opts.mode ?? MODE_RECORD;
    this.replayBranchId = opts.replayBranchId ?? null;
    this.branchFromStep = opts.branchFromStep ?? 0;
    this.dryRun = opts.dryRun ?? false;
    this.liveDebug = opts.liveDebug ?? false;
  }

  nextStep(): number {
    this.stepIndex += 1;
    return this.stepIndex;
  }
}

const als = new AsyncLocalStorage<Cursor>();

export function getCursor(): Cursor | null {
  return als.getStore() ?? null;
}

// 对应 Python 的 set_cursor:在当前异步执行上下文中生效(含其后的 await 链)
export function enterCursor(cursor: Cursor | null): void {
  als.enterWith(cursor as Cursor);
}

// 在指定游标内运行异步闭包(对应 Python with set_cursor(cursor): ...)
export function runWithCursor<T>(cursor: Cursor | null, fn: () => Promise<T>): Promise<T> {
  return als.run(cursor as Cursor, fn);
}
