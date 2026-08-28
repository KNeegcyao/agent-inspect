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
import BranchDiffView from './components/BranchDiffView.jsx'
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

function shortId(id) {
  return id ? id.slice(-8) : ''
}

// 分支索引按所属 trace 分组(跨 trace 对比下拉用)
function groupByTrace(allBranches, traces) {
  const nameById = {}
  for (const t of traces) nameById[t.id] = t.agent_name || t.id
  const groups = new Map() // trace_id -> {trace_id, trace_name, branches}
  for (const b of allBranches) {
    if (!groups.has(b.trace_id)) {
      groups.set(b.trace_id, {
        trace_id: b.trace_id,
        trace_name: b.trace_name || nameById[b.trace_id] || b.trace_id,
        branches: [],
      })
    }
    groups.get(b.trace_id).branches.push(b)
  }
  return [...groups.values()]
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
  const [debugState, setDebugState] = useState(null) // {attached, paused_at, waiting, breakpoints}
  const [pausedPayload, setPausedPayload] = useState(null) // trace.paused 载荷(完整输入)
  const [forkFromStep, setForkFromStep] = useState(null) // "在此 Fork" 定位的起点步骤
  const [diffData, setDiffData] = useState(null) // {steps, summary} | null:分支 diff 结果
  const [allBranches, setAllBranches] = useState([]) // 全局分支索引(含 trace 标签),供跨 trace 分组
  const [adoptOpen, setAdoptOpen] = useState(false) // 采纳差异弹层

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

  // 全局分支索引(跨 trace 分组对比用)。trace 列表变化时重取。
  useEffect(() => {
    api
      .listBranchesAll()
      .then(setAllBranches)
      .catch(() => {})
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
      setDebugState(null)
      setPausedPayload(null)
      setDiffData(null)
      setAdoptOpen(false)
      api.debugState(id).then(setDebugState).catch(() => {})
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
    // 全局分支优先作为单一事实源(覆盖跨 trace 对比时其它 trace 的分支)
    for (const b of allBranches) m[b.id] = b
    // 当前 trace 的分支兜底补充(例如 SSE 实时新增但全局索引尚未刷新的分支)
    for (const b of traceData?.branches || []) m[b.id] = b
    return m
  }, [traceData, allBranches])

  const groupedBranches = useMemo(
    () => groupByTrace(allBranches, traces),
    [allBranches, traces]
  )

  // ---- 实时 SSE:追加决策点 / 刷新活跃 trace / 刷新列表 / 调试状态 ----
  useEffect(() => {
    const es = openEvents((event, payload) => {
      if (!payload) return
      const td = traceDataRef.current
      const activeId = td?.trace?.id
      const onActiveTrace = activeId && payload.trace_id === activeId
      if (event === 'decision_point') {
        const bid = payload.branch_id
        const next = upsertPoint(ownPointsRef.current[bid] || [], payload)
        ownPointsRef.current[bid] = next
        setOwnPoints((prev) => ({ ...prev, [bid]: next }))
        if (onActiveTrace) {
          api.getTrace(payload.trace_id).then(setTraceData).catch(() => {})
        }
        loadTraces()
      }
      // ---- Mode C live 调试事件 ----
      if (event === 'trace.attached' && onActiveTrace) {
        api.debugState(payload.trace_id).then(setDebugState).catch(() => {})
      }
      if (event === 'trace.paused' && onActiveTrace) {
        setPausedPayload(payload)
        api.debugState(payload.trace_id).then(setDebugState).catch(() => {})
        api.getTrace(payload.trace_id).then(setTraceData).catch(() => {})
      }
      if (event === 'trace.resumed' && onActiveTrace) {
        setPausedPayload(null)
        api.debugState(payload.trace_id).then(setDebugState).catch(() => {})
      }
      if (
        (event === 'breakpoint.set' || event === 'breakpoint.removed') &&
        onActiveTrace
      ) {
        api.debugState(payload.trace_id).then(setDebugState).catch(() => {})
      }
    }, setConn)
    return () => es.close()
  }, [loadTraces])

  // ---- 活跃分支完整链路 ----
  const activeChain = useChain(activeBranchId, branchesById, getPoints, ownPoints)
  // ---- 对比分支完整链路 ----
  const compareChain = useChain(compareBranchId, branchesById, getPoints, ownPoints)

  // ---- 分支 diff:active+compare 均选中时请求后端,作为并排着色/明细的单一事实源 ----
  const diffByStep = useMemo(() => {
    const m = {}
    for (const s of diffData?.steps || []) m[s.step_index] = s
    return m
  }, [diffData])
  const diffStatus = useMemo(() => {
    const m = {}
    for (const [k, v] of Object.entries(diffByStep)) m[k] = v.status
    return m
  }, [diffByStep])
  useEffect(() => {
    if (!activeBranchId || !compareBranchId) {
      setDiffData(null)
      return undefined
    }
    let cancel = false
    api
      .branchDiff(activeBranchId, compareBranchId)
      .then((d) => {
        if (!cancel) setDiffData(d)
      })
      .catch((e) => {
        if (!cancel) setError(e.message)
      })
    return () => {
      cancel = true
    }
  }, [activeBranchId, compareBranchId, ownPoints])

  const selected = useMemo(() => {
    for (const p of [...activeChain, ...compareChain]) {
      if (p.id === selectedId) return p
    }
    return null
  }, [activeChain, compareChain, selectedId])
  const selectedDiff = selected ? diffByStep[selected.step_index] : null

  const activeBranch = activeBranchId ? branchesById[activeBranchId] : null

  // ---- Mode C 调试指令(统一捕获错误 + 刷新状态)----
  const debugCmd = useCallback(async (fn) => {
    const id = traceDataRef.current?.trace?.id
    if (!id) return
    try {
      await fn(id)
      setDebugState(await api.debugState(id))
    } catch (e) {
      setError(e.message)
    }
  }, [])
  const onDebugAttach = useCallback(() => debugCmd((id) => api.debugAttach(id)), [debugCmd])
  const onDebugPause = useCallback(() => debugCmd((id) => api.debugPause(id)), [debugCmd])
  const onDebugStep = useCallback(() => debugCmd((id) => api.debugStep(id)), [debugCmd])
  const onDebugContinue = useCallback(() => {
    debugCmd((id) => api.debugContinue(id))
    setPausedPayload(null)
  }, [debugCmd])
  const onDebugAddBreakpoint = useCallback(
    (payload) => debugCmd((id) => api.debugAddBreakpoint(id, payload)),
    [debugCmd]
  )
  const onDebugRemoveBreakpoint = useCallback(
    (bpId) => debugCmd((id) => api.debugRemoveBreakpoint(id, bpId)),
    [debugCmd]
  )
  const onDebugModify = useCallback(
    (step, field, value) => debugCmd((id) => api.debugModify(id, { step, field, value })),
    [debugCmd]
  )

  // 打开采纳差异弹层(主/对比分支均选中时可用)
  const openAdopt = useCallback(() => {
    if (!activeBranchId || !compareBranchId) return
    setAdoptOpen(true)
  }, [activeBranchId, compareBranchId])

  // 暂停点高亮:优先实时载荷,其次轮询状态
  const pausedStep =
    pausedPayload?.step_index ?? debugState?.paused_at ?? null

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
                  {groupedBranches.map((g) => (
                    <optgroup key={g.trace_id} label={g.label}>
                      {g.branches
                        .filter((b) => b.id !== activeBranchId)
                        .map((b) => (
                          <option key={b.id} value={b.id}>
                            {g.trace_id === traceData.trace.id ? '本trace' : shortId(g.trace_id)} · {originLabel(b.origin)} · 自步骤 {b.branch_from_step} ·{' '}
                            {shortId(b.id)}
                          </option>
                        ))}
                    </optgroup>
                  ))}
                </select>
                {compareBranchId && (
                  <span className="cmp-trace-tag">
                    对比 · {diffData?.trace_b ? diffData.trace_b : shortId(compareBranchId)}
                  </span>
                )}
              </div>
              <div className="toolbar-note">
                {activeBranch?.note && <span>备注:{activeBranch.note}</span>}
              </div>
              <DebugToolbar
                traceId={traceData.trace.id}
                running={traceData.trace.lifecycle === 'running'}
                debug={debugState}
                paused={pausedPayload}
                onAttach={onDebugAttach}
                onPause={onDebugPause}
                onStep={onDebugStep}
                onContinue={onDebugContinue}
                onAddBreakpoint={onDebugAddBreakpoint}
                onRemoveBreakpoint={onDebugRemoveBreakpoint}
              />
            </div>

            <div className={`canvas-area ${compareChain.length ? 'diff-mode' : ''}`}>
              {activeChain.length === 0 ? (
                <div className="empty-state">
                  <h2>该分支尚无决策点</h2>
                  <p>Agent 执行产生决策点后会实时追加到这里</p>
                </div>
              ) : compareChain.length > 0 ? (
                <BranchDiffView
                  activeChain={activeChain}
                  compareChain={compareChain}
                  diffData={diffData}
                  selectedId={selectedId}
                  onSelect={(_stepIndex, pointId) => setSelectedId(pointId)}
                  activeBranchId={activeBranchId}
                  compareBranchId={compareBranchId}
                  traceA={diffData?.trace_a}
                  traceB={diffData?.trace_b}
                  onAdopt={openAdopt}
                />
              ) : (
                <div className="canvas-col">
                  <ChainCanvas
                    points={activeChain}
                    selectedId={selectedId}
                    diffStatus={diffStatus}
                    pausedStep={pausedStep}
                    onSelect={(n) => {
                      setSelectedId(n.id)
                    }}
                  />
                </div>
              )}
            </div>
          </>
        )}
      </main>

      <aside className="inspector">
        {pausedPayload && (
          <PausePanel
            payload={pausedPayload}
            onStep={onDebugStep}
            onContinue={onDebugContinue}
            onModify={onDebugModify}
          />
        )}
        {selectedDiff?.status === 'diff' && selectedDiff.fields?.length > 0 && (
          <DiffPanel
            step={selected}
            diff={selectedDiff}
            branchA={activeBranchId}
            branchB={compareBranchId}
          />
        )}
        {selected ? (
          <PointDetails
            point={selected}
            onFork={() => setForkFromStep(selected.step_index)}
          />
        ) : (
          <div className="inspector-hint">
            点击链路中的决策点查看完整输入输出,并可发起 Fork
          </div>
        )}

        {traceData && activeBranch && (
          <ForkPanel
            traceData={traceData}
            branchId={activeBranchId}
            defaultStep={forkFromStep ?? selected?.step_index}
            onCreated={(branch) => {
              api.getTrace(traceData.trace.id).then(setTraceData).catch(() => {})
              setActiveBranchId(branch.id)
            }}
          />
        )}
      </aside>

      {adoptOpen && (
        <AdoptModal
          branchA={activeBranchId}
          branchB={compareBranchId}
          traceData={traceData}
          onClose={() => setAdoptOpen(false)}
          onCreated={(branch) => {
            api.getTrace(traceData.trace.id).then(setTraceData).catch(() => {})
            setActiveBranchId(branch.id)
            setAdoptOpen(false)
          }}
        />
      )}
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

// ---- 采纳差异弹层:只读预览修改清单,确认后复用 createFork ----
function AdoptModal({ branchA, branchB, traceData, onClose, onCreated }) {
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState(null) // {modifications, branch_a, branch_b, ...}
  const [fromStep, setFromStep] = useState(0)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  // 挂载时只读预览:把 diff 差异映射为修改清单,不创建分支
  useEffect(() => {
    let cancel = false
    setLoading(true)
    setErr(null)
    api
      .adoptDiff(branchA, branchB, { from_step: 0 })
      .then((d) => {
        if (cancel) return
        setPreview(d)
        const steps = (d.modifications || []).map((m) => m.step)
        if (steps.length) setFromStep(Math.min(...steps))
      })
      .catch((e) => {
        if (!cancel) setErr(e.message)
      })
      .finally(() => {
        if (!cancel) setLoading(false)
      })
    return () => {
      cancel = true
    }
  }, [branchA, branchB])

  const mods = preview?.modifications || []

  const confirm = async () => {
    setErr(null)
    setBusy(true)
    try {
      const res = await api.createFork({
        trace_id: traceData.trace.id,
        branch_id: branchA,
        from_step: parseInt(fromStep, 10),
        modifications: mods,
        note: note || undefined,
      })
      onCreated(res.branch)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal adopt-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>采纳差异为 Fork</h3>
          <button className="ghost-btn small" onClick={onClose} title="关闭">
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="kv-row">
            <span>主分支</span>
            <code>
              {preview?.trace_a
                ? `${preview.trace_a} · ${branchA?.slice(-8)}`
                : branchA?.slice(-8)}
            </code>
          </div>
          <div className="kv-row">
            <span>对比分支</span>
            <code>
              {preview?.trace_b
                ? `${preview.trace_b} · ${branchB?.slice(-8)}`
                : branchB?.slice(-8)}
            </code>
          </div>
          {preview?.trace_id_a &&
            preview?.trace_id_b &&
            preview.trace_id_a !== preview.trace_id_b && (
              <div className="adopt-cross-trace">
                修改值取自另一条 trace(对比分支 · {preview.trace_b}),将应用到当前 trace 的新分支
              </div>
            )}
          {loading ? (
            <div className="empty-hint">正在计算采纳修改…</div>
          ) : err ? (
            <div className="err-block">{err}</div>
          ) : mods.length === 0 ? (
            <div className="empty-hint">对比分支无可用差异可采纳</div>
          ) : (
            <>
              <div className="adopt-list">
                {mods.map((m, i) => (
                  <div key={i} className="adopt-item">
                    <span className="adopt-step">#{m.step}</span>
                    <code className="adopt-field">{m.field}</code>
                    <pre className="adopt-value">{JSON.stringify(m.value, null, 2)}</pre>
                  </div>
                ))}
              </div>
              <label className="field">
                <span>分支起点步骤(该步骤起真实执行,修改均位于其后)</span>
                <input
                  type="number"
                  min="0"
                  value={fromStep}
                  onChange={(e) => setFromStep(e.target.value)}
                />
              </label>
              <label className="field">
                <span>备注(可选)</span>
                <input value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
            </>
          )}
        </div>
        <div className="modal-foot">
          <button className="ghost-btn" onClick={onClose}>
            取消
          </button>
          <button
            className="fork-btn"
            disabled={busy || loading || !!err || mods.length === 0}
            onClick={confirm}
          >
            {busy ? '创建中…' : '确认创建 Fork'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- Mode C 调试工具条(Attach / 断点 / Pause / Step / Continue)----
function DebugToolbar({
  running,
  debug,
  paused,
  onAttach,
  onPause,
  onStep,
  onContinue,
  onAddBreakpoint,
  onRemoveBreakpoint,
}) {
  const [bpOpen, setBpOpen] = useState(false)
  const [bpKind, setBpKind] = useState('')
  const [bpCond, setBpCond] = useState('')
  const [err, setErr] = useState(null)
  const attached = !!debug?.attached
  const waiting = !!debug?.waiting || paused != null
  const bps = debug?.breakpoints || []

  const submitBp = async () => {
    setErr(null)
    if (!bpKind && !bpCond.trim()) {
      setErr('需指定类型或命中子串')
      return
    }
    try {
      await onAddBreakpoint({
        kind: bpKind || undefined,
        condition: bpCond.trim() || undefined,
      })
      setBpKind('')
      setBpCond('')
      setBpOpen(false)
    } catch (e) {
      setErr(e.message)
    }
  }

  return (
    <div className="debug-toolbar">
      <span className="debug-label">调试</span>
      {!running ? (
        <span className="debug-hint">仅运行中可附加</span>
      ) : !attached ? (
        <button className="debug-btn attach" onClick={onAttach}>
          Attach
        </button>
      ) : (
        <>
          <span className="debug-attached">已附加</span>
          <button
            className="debug-btn"
            onClick={() => {
              setBpOpen((v) => !v)
              setErr(null)
            }}
          >
            断点{bps.length ? `(${bps.length})` : ''}
          </button>
          <button className="debug-btn" disabled={waiting} onClick={onPause}>
            Pause
          </button>
          <button className="debug-btn" disabled={!waiting} onClick={onStep}>
            Step
          </button>
          <button
            className="debug-btn primary"
            disabled={!waiting}
            onClick={onContinue}
          >
            Continue
          </button>
        </>
      )}

      {attached && (
        <div className="debug-bps">
          {bps.map((b) => (
            <span
              key={b.id}
              className="bp-chip"
              title={b.condition ? `命中:"${b.condition}"` : ''}
            >
              {b.kind ? kindLabel(b.kind) : '输入'}
              {b.condition ? `:"${b.condition}"` : ''}
              <button
                className="bp-del"
                title="删除断点"
                onClick={() => onRemoveBreakpoint(b.id)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {attached && bpOpen && (
        <div className="bp-form">
          <select
            value={bpKind}
            onChange={(e) => setBpKind(e.target.value)}
          >
            <option value="">任意类型</option>
            <option value="llm">LLM</option>
            <option value="tool">工具</option>
          </select>
          <input
            placeholder="命中子串(如 secret)"
            value={bpCond}
            onChange={(e) => setBpCond(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submitBp()}
          />
          <button className="debug-btn primary" onClick={submitBp}>
            添加
          </button>
          {err && <span className="debug-err">{err}</span>}
        </div>
      )}
    </div>
  )
}

// ---- 暂停点面板:完整输入检查 + 输入可编辑(应用修改并继续)----
function PausePanel({ payload, onStep, onContinue, onModify }) {
  const [field, setField] = useState('input_context.messages[0].content')
  const [valueText, setValueText] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  const applyModify = async () => {
    setErr(null)
    if (!field.trim() || !valueText.trim()) {
      setErr('需填写字段路径与新值(JSON)')
      return
    }
    let value
    try {
      value = JSON.parse(valueText)
    } catch {
      setErr('新值不是合法 JSON')
      return
    }
    setBusy(true)
    try {
      await onModify(payload.step_index, field.trim(), value)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel pause-panel">
      <div className="panel-head">
        <h3>已暂停 · 步骤 {payload.step_index}</h3>
        <span className={`pause-kind ${payload.kind}`}>
          {kindLabel(payload.kind)}
        </span>
      </div>
      <div className="kv-row">
        <span>agent</span>
        <code>{payload.agent_id}</code>
      </div>
      <JsonBlock label="完整输入(检查用)" data={payload.input_context} />
      <div className="field">
        <span>修改字段(JSON 路径,可省略 input_context. 前缀)</span>
        <input
          value={field}
          onChange={(e) => setField(e.target.value)}
          placeholder="input_context.messages[0].content"
        />
      </div>
      <div className="field">
        <span>新值(JSON)</span>
        <textarea
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          placeholder='例如 "新的 prompt"'
        />
      </div>
      {err && <div className="err-block">{err}</div>}
      <div className="pause-actions">
        <button className="debug-btn" onClick={onStep}>
          单步
        </button>
        <button className="debug-btn" onClick={onContinue}>
          继续
        </button>
        <button
          className="debug-btn primary"
          disabled={busy}
          onClick={applyModify}
        >
          {busy ? '应用中…' : '应用修改并继续'}
        </button>
      </div>
    </section>
  )
}

// ---- 分支 diff 字段级明细面板(选中差异步骤时展示)----
const DIFF_TAG = { changed: '改', added: '增', removed: '删' }

function DiffPanel({ step, diff, branchA, branchB }) {
  return (
    <section className="panel diff-panel">
      <div className="panel-head">
        <h3>字段差异 · 步骤 {step.step_index}</h3>
        <span className="diff-badge">{kindLabel(step.kind)}</span>
      </div>
      <div className="kv-row">
        <span>对比</span>
        <span className="diff-heads">
          <b>左 · {branchA?.slice(-8)}</b>
          <b>右 · {branchB?.slice(-8)}</b>
        </span>
      </div>
      {diff.fields.map((f, i) => {
        const showLeft = f.status !== 'added'
        const showRight = f.status !== 'removed'
        return (
          <div key={i} className="diff-row">
            <div className="diff-path">
              <span className={`diff-dot ${f.status}`} />
              <code>{f.path}</code>
              <span className={`diff-tag ${f.status}`}>{DIFF_TAG[f.status]}</span>
            </div>
            <div className="diff-cells">
              <pre className={showLeft ? '' : 'diff-none'}>
                {showLeft ? JSON.stringify(f.left, null, 2) : '—'}
              </pre>
              <pre className={showRight ? '' : 'diff-none'}>
                {showRight ? JSON.stringify(f.right, null, 2) : '—'}
              </pre>
            </div>
          </div>
        )
      })}
    </section>
  )
}
