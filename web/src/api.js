// 内嵌调试服务 REST/SSE 客户端。API 契约见 agent_inspect/_server/app.py。

async function parse(r) {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const b = await r.json()
      if (b && b.error) msg = b.error
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  listTraces(lifecycle) {
    const q = lifecycle && lifecycle !== 'all' ? `?lifecycle=${lifecycle}` : ''
    return fetch(`/api/traces${q}`).then(parse)
  },
  getTrace(id) {
    return fetch(`/api/traces/${encodeURIComponent(id)}`).then(parse)
  },
  exportTraceUrl(id) {
    return `/api/traces/${encodeURIComponent(id)}/export`
  },
  getBranchPoints(branchId) {
    return fetch(`/api/branches/${encodeURIComponent(branchId)}/points`).then(parse)
  },
  listBranchesAll() {
    return fetch('/api/branches').then(parse)
  },
  branchDiff(branchA, branchB) {
    return fetch(
      `/api/branches/${encodeURIComponent(branchA)}/diff/${encodeURIComponent(branchB)}`
    ).then(parse)
  },
  adoptDiff(branchA, branchB, payload) {
    return fetch(
      `/api/branches/${encodeURIComponent(branchA)}/diff/${encodeURIComponent(branchB)}/adopt`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }
    ).then(parse)
  },
  createFork(payload) {
    return fetch('/api/forks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(parse)
  },
  importTraces(payload) {
    return fetch('/api/traces/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(parse)
  },
  pushTrace(traceId, endpoint, timeout) {
    return fetch(`/api/traces/${encodeURIComponent(traceId)}/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint, timeout }),
    }).then(parse)
  },
  // ---- Mode C live 调试 ----
  debugAttach(traceId) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/attach`, {
      method: 'POST',
    }).then(parse)
  },
  debugState(traceId) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/state`).then(parse)
  },
  debugAddBreakpoint(traceId, payload) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/breakpoints`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(parse)
  },
  debugRemoveBreakpoint(traceId, bpId) {
    return fetch(
      `/api/debug/${encodeURIComponent(traceId)}/breakpoints/${encodeURIComponent(bpId)}`,
      { method: 'DELETE' }
    ).then(parse)
  },
  debugPause(traceId) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/pause`, {
      method: 'POST',
    }).then(parse)
  },
  debugStep(traceId, atStep) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/step`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(atStep == null ? {} : { at_step: atStep }),
    }).then(parse)
  },
  debugContinue(traceId, atStep) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/continue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(atStep == null ? {} : { at_step: atStep }),
    }).then(parse)
  },
  debugModify(traceId, payload) {
    return fetch(`/api/debug/${encodeURIComponent(traceId)}/modify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(parse)
  },
}

// SSE 事件流:event = "decision_point" | "ping";payload 为 JSON。
export function openEvents(onEvent, onStatus) {
  const es = new EventSource('/api/events')
  es.addEventListener('decision_point', (e) => {
    try {
      onEvent('decision_point', JSON.parse(e.data))
    } catch {
      /* ignore malformed */
    }
  })
  es.addEventListener('ping', () => onEvent && onEvent('ping', null))
  es.onopen = () => onStatus && onStatus('open')
  es.onerror = () => onStatus && onStatus('error')
  return es
}
