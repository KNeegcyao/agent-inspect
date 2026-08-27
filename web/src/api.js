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
  getBranchPoints(branchId) {
    return fetch(`/api/branches/${encodeURIComponent(branchId)}/points`).then(parse)
  },
  createFork(payload) {
    return fetch('/api/forks', {
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
