// 分支完整链路构造:共享前缀(继承自父分支) + 本分支后缀。
//
// Fork 分支只记录 branch_from_step 之后的决策点,前缀步骤存于父分支
// (spec fork.前缀共享:不向 fork 分支复制历史)。这里沿 parent_branch_id
// 递归回溯,把完整链路拼出来,并标记 inherited(共享前缀)节点。

const BIG = Number.MAX_SAFE_INTEGER

async function chainSteps(branch, upto, branchesById, getPoints, inherited) {
  if (!branch || upto <= 0) return []
  const own = (await getPoints(branch.id))
    .filter((p) => p.step_index < upto)
    .map((p) => ({ ...p, inherited: !!inherited, branch_id: branch.id }))

  const parent = branch.parent_branch_id
    ? branchesById[branch.parent_branch_id]
    : null
  const need = Math.min(branch.branch_from_step, upto)
  if (need > 0 && parent) {
    const prefix = await chainSteps(parent, need, branchesById, getPoints, true)
    return [...prefix, ...own]
  }
  return own
}

export async function buildChain(branch, branchesById, getPoints) {
  if (!branch) return []
  return chainSteps(branch, BIG, branchesById, getPoints, false)
}

// ---- 展示辅助 ----

export function kindLabel(kind) {
  return kind === 'tool' ? '工具' : 'LLM'
}

export function originLabel(origin) {
  return origin === 'fork' ? 'Fork' : '记录'
}

export function lifecycleLabel(lifecycle) {
  return (
    { running: '进行中', done: '完成', aborted: '中止' }[lifecycle] || lifecycle
  )
}

export function outputPreview(p, max = 60) {
  const out = p.output
  if (out == null) return '(无输出)'
  const raw =
    typeof out === 'object' ? JSON.stringify(out) : String(out)
  return raw.length > max ? raw.slice(0, max) + '…' : raw
}

export function inputPreview(p, max = 60) {
  const ctx = p.input_context
  if (!ctx) return ''
  const raw = JSON.stringify(ctx)
  return raw.length > max ? raw.slice(0, max) + '…' : raw
}

export function fmtTime(ts) {
  if (!ts) return ''
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts)
  try {
    return d.toLocaleTimeString()
  } catch {
    return String(ts)
  }
}

export function fmtLatency(meta) {
  const ms = meta && meta.latency_ms
  if (ms == null) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}


// 链路统计摘要:耗时合计 + token 合计(usage 优先,meta tokens 回退)。
// 耗时与 token 各自独立判定"有数据";无任何统计返回 null。
export function summarizeChain(points) {
  let latencyMs = null
  let tokens = null
  for (const p of points) {
    const lat = p.meta && p.meta.latency_ms
    if (typeof lat === 'number') latencyMs = (latencyMs ?? 0) + lat
    const usage = p.output && p.output.usage && p.output.usage.total_tokens
    const metaIn = p.meta && p.meta.tokens_in
    const metaOut = p.meta && p.meta.tokens_out
    let t = null
    if (typeof usage === 'number') t = usage
    else if (typeof metaIn === 'number' || typeof metaOut === 'number') {
      t = (metaIn ?? 0) + (metaOut ?? 0)
    }
    if (t != null) tokens = (tokens ?? 0) + t
  }
  if (latencyMs == null && tokens == null) return null
  return { latencyMs, tokens }
}
