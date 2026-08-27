import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, openEvents } from './api.js'
import {
  buildChain,
  fmtLatency,
  fmtTime,
  kindLabel,
  lifecycleLabel,
  originLabel,
} from './chain.js'
import ChainCanvas from './components/ChainCanvas.jsx'

const LIFE_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '进行中' },
  { value: 'done', label: '完成' },
  { value: 'aborted', label: '中止' },
]

// 按 id 去重并按 step_index 排序的追加
function upsertPoint(list, p) {
  const m = new Map(list.map((x) => [x.id, x]))
  m.set(p.id, p)
  return [...m.values()].sort((a, b) => a.step_index - b.step_index)
}

// 分支来源徽标
function OriginBadge({ branch }) {
  const origin = branch.origin || 'record'
  return (
    <span className={`origin-badge ${origin}`}>
      {origin === 'fork' ? 'Fork' : '记录'}
    </span>
  )
}

export default function App() {
  const [traces, setTraces] = useState([])
  const [lifeFilter, setLifeFilter] = useState('all')
  const [traceData, setTraceData] = useState(null) // {trace, branches}
  const [activeBranchId, setActiveBranchId] = useState(null)
  const [compareBranchId, setCompareBranchId] = useState(null)
  const [ownPoints, setOwnPoints] = useState({}) // branchId -> points[]
  const [selectedId, setSelectedId] = useState(null)
  const [conn, setConn] = useState('connecting')
  const [error, setError] = useState(null)

  // 供稳定 SSE 回调读取的 ref(避免因依赖变化反复重连)
  const ownPointsRef = useRef(ownPoints)
  const traceDataRef = useRef(traceData)
  traceDataRef.current = traceData

  // ---- trace 列表 ----
  const loadTraces = useCallback(async () => {
    try {
      setTraces(await api.listTraces(lifeFilter))
    } catch (e) {
      setError(e.message)
    }
  }, [lifeFilter])
  useEffect(() => {
    loadTraces()
  }, [loadTraces])

  // ---- 选中 trace ----
  const selectTrace = useCallback(async (id) => {
    setError(null)
    try {
      const data = await api.getTrace(id)
      setTraceData(data)
      setOwnPoints({})
      ownPointsRef.current = {}
      setSelectedId(null)
      setCompareBranchId(null)
      const root = data.trace.root_branch_id
      const hasRoot = root && data.branches.some((b) => b.id === root)
      setActiveBranchId(hasRoot ? root : data.branches[0]?.id || null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  // ---- 分支决策点缓存读取 ----
  const getPoints = useCallback(async (branchId) => {
    const cached = ownPointsRef.current[branchId]
    if (cached) return cached
    const pts = await api.getBranchPoints(branchId)
    ownPointsRef.current[branchId] = pts
    setOwnPoints((prev) => ({ ...prev, [branchId]: pts }))
    return pts
  }, [])

  const branchesById = useMemo(() => {
    const m = {}
    for (const b of traceData?.branches || []) m[b.id] = b
    return m
  }, [traceData])

  // ---- 实时 SSE:追加决策点 / 刷新活跃 trace / 刷新列表 ----
  useEffect(() => {
    const es = openEvents((event, payload) => {
      if (event !== 'decision_point' || !payload) return
      const bid = payload.branch_id
      const next = upsertPoint(ownPointsRef.current[bid] || [], payload)
      ownPointsRef.current[bid] = next
      setOwnPoints((prev) => ({ ...prev, [bid]: next }))
      const td = traceDataRef.current
      if (td && payload.trace_id === td.trace.id) {
        api.getTrace(payload.trace_id).then(setTraceData).catch(() => {})
      }
      loadTraces()
    }, setConn)
    return () => es.close()
  }, [loadTraces])

  // ---- 活跃分支完整链路 ----
  const activeChain = useChain(activeBranchId, branchesById, getPoints, ownPoints)
  // ---- 对比分支完整链路 ----
  const compareChain = useChain(compareBranchId, branchesById, getPoints, ownPoints)

  // 分歧步骤:两个链同 step_index 输出不同(或仅一侧有)
  const divergentSteps = useMemo(() => {
    const d = new Set()
    if (!compareChain.length) return d
    const byStep = (chain) => {
      const m = new Map()
      for (const p of chain) m.set(p.step_index, p)
      return m
    }
    const a = byStep(activeChain)
    const b = byStep(compareChain)
    for (const s of new Set([...a.keys(), ...b.keys()])) {
      const oa = JSON.stringify(a.get(s)?.output ?? null)
      const ob = JSON.stringify(b.get(s)?.output ?? null)
      if (oa !== ob) d.add(s)
    }
    return d
  }, [activeChain, compareChain])

  const selected = useMemo(() => {
    for (const p of [...activeChain, ...compareChain]) {
      if (p.id === selectedId) return p
    }
    return null
  }, [activeChain, compareChain, selectedId])

  const activeBranch = activeBranchId ? branchesById[activeBranchId] : null

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="app-title">
          <h1>Agent-Inspect</h1>
          <span className={`conn conn-${conn}`}>
            {conn === 'open' ? '实时' : conn === 'error' ? '已断开' : '连接中'}
          </span>
        </header>

        <div className="filters">
          {LIFE_FILTERS.map((f) => (
            <button
              key={f.value}
              className={`chip ${lifeFilter === f.value ? 'chip-active' : ''}`}
              onClick={() => setLifeFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="trace-list">
          {traces.length === 0 && <div className="empty-hint">暂无 trace</div>}
          {traces.map((t) => (
            <button
              key={t.id}
              className={`trace-item ${t.id === traceData?.trace?.id ? 'trace-active' : ''}`}
              onClick={() => selectTrace(t.id)}
            >
              <div className="trace-line">
                <span className="trace-name">{t.agent_name || t.id}</span>
                <span className={`life life-${t.lifecycle}`}>
                  {lifecycleLabel(t.lifecycle)}
                </span>
              </div>
              <div className="trace-sub">
                <span>{fmtTime(t.started_at)}</span>
                <span>{t.id.slice(-8)}</span>
              </div>
            </button>
          ))}
        </div>

        <button className="ghost-btn" onClick={loadTraces}>
          刷新列表
        </button>
      </aside>

      <main className="main">
        {!traceData ? (
          <div className="empty-state">
            <h2>选择左侧一条 trace</h2>
            <p>或运行 Agent 后自动出现在列表</p>
          </div>
        ) : (
          <>
            <div className="toolbar">
              <div className="branch-pick">
                <label>主分支</label>
                <select
                  value={activeBranchId || ''}
                  onChange={(e) => setActiveBranchId(e.target.value || null)}
                >
                  {traceData.branches.map((b) => (
                    <option key={b.id} value={b.id}>
                      {originLabel(b.origin)} · 自步骤 {b.branch_from_step} ·{' '}
                      {b.id.slice(-8)}
                    </option>
                  ))}
                </select>
                {activeBranch && <OriginBadge branch={activeBranch} />}
              </div>
              <div className="branch-pick">
                <label>对比分支</label>
                <select
                  value={compareBranchId || ''}
                  onChange={(e) => setCompareBranchId(e.target.value || null)}
                >
                  <option value="">(无)</option>
                  {traceData.branches
                    .filter((b) => b.id !== activeBranchId)
                    .map((b) => (
                      <option key={b.id} value={b.id}>
                        {originLabel(b.origin)} · 自步骤 {b.branch_from_step} ·{' '}
                        {b.id.slice(-8)}
                      </option>
                    ))}
                </select>
              </div>
              <div className="toolbar-note">
                {activeBranch?.note && <span>备注:{activeBranch.note}</span>}
              </div>
            </div>

            <div className={`canvas-area ${compareChain.length ? 'side-by-side' : ''}`}>
              {activeChain.length === 0 ? (
                <div className="empty-state">
                  <h2>该分支尚无决策点</h2>
                  <p>Agent 执行产生决策点后会实时追加到这里</p>
                </div>
              ) : (
                <div className="canvas-col">
                  {compareChain.length > 0 && (
                    <div className="col-label">主分支 · {activeBranch?.id.slice(-8)}</div>
                  )}
                  <ChainCanvas
                    points={activeChain}
                    selectedId={selectedId}
                    divergentSteps={divergentSteps}
                    onSelect={(n) => {
                      setSelectedId(n.id)
                    }}
                  />
                </div>
              )}

              {compareChain.length > 0 && (
                <div className="canvas-col">
                  <div className="col-label">
                    对比分支 · {compareBranchId?.slice(-8)}
                    {divergentSteps.size > 0 && (
                      <span className="divergence-count">
                        {divergentSteps.size} 处分歧
                      </span>
                    )}
                  </div>
                  <ChainCanvas
                    points={compareChain}
                    selectedId={selectedId}
                    divergentSteps={divergentSteps}
                    onSelect={(n) => setSelectedId(n.id)}
                  />
                </div>
              )}
            </div>
          </>
        )}
      </main>

      <aside className="inspector">
        {selected ? (
          <PointDetails point={selected} onFork={() => setFromStep(selected.step_index)} />
        ) : (
          <div className="inspector-hint">
            点击链路中的决策点查看完整输入输出,并可发起 Fork
          </div>
        )}

        {traceData && activeBranch && (
          <ForkPanel
            traceData={traceData}
            branchId={activeBranchId}
            defaultStep={selected?.step_index}
            onCreated={(branch) => {
              api.getTrace(traceData.trace.id).then(setTraceData).catch(() => {})
              setActiveBranchId(branch.id)
            }}
          />
        )}
      </aside>
    </div>
  )
}

// ---- 分支完整链路 hook(ownPoints 变化时重建,实现实时追加)----
function useChain(branchId, branchesById, getPoints, ownPoints) {
  const [chain, setChain] = useState([])
  useEffect(() => {
    let cancel = false
    const branch = branchId ? branchesById[branchId] : null
    if (!branch) {
      setChain([])
      return undefined
    }
    buildChain(branch, branchesById, getPoints).then((pts) => {
      if (!cancel) setChain(pts)
    })
    return () => {
      cancel = true
    }
  }, [branchId, branchesById, getPoints, ownPoints])
  return chain
}

// ---- 决策点详情 ----
function PointDetails({ point, onFork }) {
  const kind = point.kind
  const title = `${kindLabel(kind)} · 步骤 ${point.step_index}`
  return (
    <section className="panel point-details">
      <div className="panel-head">
        <h3>{title}</h3>
        <button className="fork-btn" onClick={onFork}>
          在此 Fork
        </button>
      </div>
      <div className="kv-row">
        <span>agent</span>
        <code>{point.agent_id}</code>
      </div>
      <div className="kv-row">
        <span>分支</span>
        <code>{point.branch_id?.slice(-8)}</code>
      </div>
      <div className="kv-row">
        <span>耗时</span>
        <code>{fmtLatency(point.meta)}</code>
      </div>
      <div className="kv-row">
        <span>共享前缀</span>
        <code>{point.inherited ? '是' : '否'}</code>
      </div>
      <JsonBlock label="输入" data={point.input_context} />
      <JsonBlock label="输出" data={point.output} />
      {point.meta?.error && (
        <div className="err-block">
          <b>错误</b>
          <pre>{String(point.meta.error)}</pre>
        </div>
      )}
    </section>
  )
}

function JsonBlock({ label, data }) {
  return (
    <div className="json-block">
      <div className="json-label">{label}</div>
      <pre>{data == null ? '(无)' : JSON.stringify(data, null, 2)}</pre>
    </div>
  )
}

// ---- Fork 面板 ----
function ForkPanel({ traceData, branchId, defaultStep, onCreated }) {
  const [open, setOpen] = useState(false)
  const [fromStep, setFromStep] = useState(defaultStep ?? 0)
  const [mods, setMods] = useState([]) // {key, step, field, valueText}
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (defaultStep != null) setFromStep(defaultStep)
  }, [defaultStep])

  const addMod = () => {
    setMods((prev) => [
      ...prev,
      {
        key: Math.random().toString(36).slice(2),
        step: fromStep,
        field: '',
        valueText: '',
      },
    ])
  }

  const patchMod = (key, patch) =>
    setMods((prev) => prev.map((m) => (m.key === key ? { ...m, ...patch } : m)))

  const removeMod = (key) => setMods((prev) => prev.filter((m) => m.key !== key))

  const submit = async () => {
    setErr(null)
    const parsed = []
    for (const m of mods) {
      let value
      try {
        value = JSON.parse(m.valueText)
      } catch {
        setErr(`步骤 ${m.step} 的修改值不是合法 JSON`)
        return
      }
      if (!m.field.trim()) {
        setErr(`步骤 ${m.step} 缺少修改字段`)
        return
      }
      parsed.push({ step: parseInt(m.step, 10), field: m.field.trim(), value })
    }
    setBusy(true)
    try {
      const res = await api.createFork({
        trace_id: traceData.trace.id,
        branch_id: branchId,
        from_step: parseInt(fromStep, 10),
        modifications: parsed,
        note: note || undefined,
      })
      onCreated(res.branch)
      setOpen(false)
      setMods([])
      setNote('')
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <section className="panel fork-panel">
        <button className="fork-btn wide" onClick={() => setOpen(true)}>
          发起 Fork
        </button>
      </section>
    )
  }

  return (
    <section className="panel fork-panel">
      <div className="panel-head">
        <h3>发起 Fork</h3>
        <button className="ghost-btn small" onClick={() => setOpen(false)}>
          收起
        </button>
      </div>

      <label className="field">
        <span>分支起点步骤(0..前缀回放,该步骤起真调)</span>
        <input
          type="number"
          min="0"
          value={fromStep}
          onChange={(e) => setFromStep(e.target.value)}
        />
      </label>

      <div className="field">
        <span>注入修改(可多条;field ∈ output 或 input_context.路径)</span>
        {mods.length === 0 && <div className="empty-hint">尚未添加修改(将原样重跑后缀)</div>}
        {mods.map((m) => (
          <div key={m.key} className="mod-row">
            <input
              className="mod-step"
              type="number"
              min="0"
              value={m.step}
              onChange={(e) => patchMod(m.key, { step: e.target.value })}
            />
            <input
              className="mod-field"
              placeholder="output / input_context.messages[0].content"
              value={m.field}
              onChange={(e) => patchMod(m.key, { field: e.target.value })}
            />
            <button
              className="ghost-btn small"
              onClick={() => removeMod(m.key)}
              title="移除"
            >
              ×
            </button>
            <textarea
              placeholder='修改值(JSON),例如 {"content": "新的 prompt"}'
              value={m.valueText}
              onChange={(e) => patchMod(m.key, { valueText: e.target.value })}
            />
          </div>
        ))}
        <button className="ghost-btn small" onClick={addMod}>
          + 添加修改
        </button>
      </div>

      <label className="field">
        <span>备注(可选)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如:修正 prompt 拼写" />
      </label>

      {err && <div className="err-block">{err}</div>}

      <button className="fork-btn wide" disabled={busy} onClick={submit}>
        {busy ? '创建中…' : '创建 Fork 分支'}
      </button>
    </section>
  )
}
