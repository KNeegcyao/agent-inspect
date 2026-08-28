import { useMemo } from 'react'

const STATUS_LABEL = {
  same: '同',
  diff: '异',
  only_left: '仅左',
  only_right: '仅右',
}

function kindLabel(kind) {
  if (kind === 'llm') return 'LLM'
  if (kind === 'tool') return 'Tool'
  return kind || 'unknown'
}

function outputSnippet(point) {
  if (!point) return null
  const out = point.output
  if (out == null) return '(no output)'
  if (typeof out === 'string') return out
  if (out.content != null) return String(out.content)
  return JSON.stringify(out).slice(0, 200)
}

function DiffCard({ point, branchId, selected, onClick }) {
  if (!point) {
    return (
      <div className="diff-card diff-card-empty" onClick={onClick}>
        <span className="diff-card-muted">—</span>
      </div>
    )
  }
  return (
    <div
      className={`diff-card ${selected ? 'selected' : ''} ${point.inherited ? 'inherited' : ''}`}
      onClick={onClick}
    >
      <div className="diff-card-head">
        <span className="diff-card-kind">{kindLabel(point.kind)}</span>
        <span className="diff-card-agent">{point.agent_id}</span>
        {point.inherited && <span className="diff-card-tag">继承</span>}
      </div>
      <pre className="diff-card-output">{outputSnippet(point)}</pre>
      <div className="diff-card-branch">{branchId?.slice(-8)}</div>
    </div>
  )
}

export default function BranchDiffView({
  activeChain,
  compareChain,
  diffData,
  selectedId,
  onSelect,
  activeBranchId,
  compareBranchId,
  traceA,
  traceB,
}) {
  const leftByStep = useMemo(() => {
    const m = {}
    for (const p of activeChain) m[p.step_index] = p
    return m
  }, [activeChain])

  const rightByStep = useMemo(() => {
    const m = {}
    for (const p of compareChain) m[p.step_index] = p
    return m
  }, [compareChain])

  const steps = diffData?.steps || []

  return (
    <div className="branch-diff-view">
      <div className="diff-view-header">
        <span>步骤</span>
        <span>
          主分支 · {traceA || activeBranchId?.slice(-8)}
          {traceA ? <em className="diff-head-tag">{activeBranchId?.slice(-8)}</em> : null}
        </span>
        <span>
          对比分支 · {traceB || compareBranchId?.slice(-8)}
          {traceB ? <em className="diff-head-tag">{compareBranchId?.slice(-8)}</em> : null}
        </span>
        <span>状态</span>
      </div>
      {steps.map((s) => {
        const left = leftByStep[s.step_index]
        const right = rightByStep[s.step_index]
        const status = s.status
        return (
          <div key={s.step_index} className={`diff-step-row ${status}`}>
            <div className="diff-step-index">#{s.step_index}</div>
            <DiffCard
              point={left}
              branchId={activeBranchId}
              selected={left && left.id === selectedId}
              onClick={() => left && onSelect(s.step_index, left.id)}
            />
            <DiffCard
              point={right}
              branchId={compareBranchId}
              selected={right && right.id === selectedId}
              onClick={() => right && onSelect(s.step_index, right.id)}
            />
            <div className={`diff-step-status ${status}`}>{STATUS_LABEL[status]}</div>
          </div>
        )
      })}
    </div>
  )
}
