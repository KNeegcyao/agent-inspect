import React, { useEffect, useMemo, useRef, useState } from 'react'
import { hierarchy, tree } from 'd3-hierarchy'
import { kindLabel, outputPreview } from '../chain.js'

const NODE_W = 300
const NODE_H = 66
const ROW_GAP = 26 // 纵向:深度方向(父子步骤)间距
const COL_GAP = 40 // 横向:兄弟分叉间距
const PAD = 50

const KIND_COLORS = { llm: '#3b82f6', tool: '#f59e0b', default: '#8b5cf6' }

// 画布绘制色:从 CSS 变量读取(随主题切换),读取失败兜底深色原值
function themeColors() {
  const css = getComputedStyle(document.documentElement)
  const v = (name, fb) => css.getPropertyValue(name).trim() || fb
  return {
    nodeBg: v('--canvas-node-bg', '#121a2c'),
    nodeTitle: v('--canvas-node-title', '#cbd5e1'),
    nodeText: v('--canvas-node-text', '#e2e8f0'),
    nodeMuted: v('--canvas-node-muted', '#64748b'),
    edge: v('--canvas-edge', '#334155'),
    error: '#f87171',
    selected: '#7dd3fc',
  }
}

// ---- 布局:D3-hierarchy tree(按 cause_edge 组树),Canvas 渲染节点 ----
// 深度纵向(步骤自上而下),兄弟分叉横向展开——线性链为垂直步骤列表。
function computeLayout(points) {
  if (!points.length) {
    return { nodes: [], edges: [], width: PAD * 2, height: PAD * 2 }
  }
  const byId = new Map(points.map((p) => [p.id, { ...p, children: [] }]))
  const roots = []
  for (const p of byId.values()) {
    const causes = (p.cause_edge || []).filter((c) => byId.has(c))
    if (!causes.length) roots.push(p)
    for (const c of causes) byId.get(c).children.push(p)
  }
  let root
  if (roots.length === 1) root = roots[0]
  else root = { id: '__virtual__', kind: 'root', children: roots }

  const t = tree().nodeSize([NODE_W + COL_GAP, NODE_H + ROW_GAP])
  // tree() 就地计算 x/y 并返回带 .each/.descendants 的 hierarchy 节点;
  // 若不接收返回值,下面 root.each 会抛 "r.each is not a function"。
  const h = t(hierarchy(root))

  // 先收集原始坐标:x=兄弟横向(d3 以 0 居中,可负),y=深度纵向
  const raw = []
  h.each((n) => {
    if (n.data.id === '__virtual__') return
    raw.push({ data: n.data, left: PAD + n.x, top: PAD + n.y })
  })
  // 归一化:最左节点对齐到 PAD,避免整棵树偏出画布
  const minX = raw.length ? Math.min(...raw.map((r) => r.left)) : PAD

  const nodes = []
  const pos = new Map()
  let maxW = 0
  let maxH = 0
  for (const r of raw) {
    const left = r.left - minX + PAD
    const top = r.top
    maxW = Math.max(maxW, left)
    maxH = Math.max(maxH, top)
    const node = {
      ...r.data,
      x: left,
      y: top,
      rect: { x: left, y: top, w: NODE_W, h: NODE_H },
    }
    nodes.push(node)
    pos.set(node.id, node)
  }
  const edges = []
  for (const node of nodes) {
    const src = byId.get(node.id)
    for (const child of src.children || []) {
      const cp = pos.get(child.id)
      if (!cp) continue
      edges.push({
        x1: node.x + NODE_W / 2,
        y1: node.y + NODE_H,
        x2: cp.x + NODE_W / 2,
        y2: cp.y,
      })
    }
  }
  return {
    nodes,
    edges,
    width: Math.max(PAD * 2, maxW + NODE_W + PAD),
    height: Math.max(PAD * 2, maxH + NODE_H + PAD),
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function drawEdges(ctx, edges, colors) {
  ctx.save()
  ctx.strokeStyle = colors.edge
  ctx.lineWidth = 1.2
  for (const e of edges) {
    ctx.beginPath()
    ctx.moveTo(e.x1, e.y1)
    ctx.lineTo(e.x2, e.y2)
    ctx.stroke()
  }
  ctx.restore()
}

// diff 状态描边色:same 用默认 kind 色,diff=rose,only_left=amber,only_right=blue
const DIFF_COLORS = {
  diff: '#fb7185',
  only_left: '#fbbf24',
  only_right: '#60a5fa',
}

function drawNode(ctx, node, { selected, diffStatus, colors }) {
  const r = node.rect
  const color = KIND_COLORS[node.kind] || KIND_COLORS.default
  const hasErr = node.meta && node.meta.error
  const status = diffStatus ? diffStatus[node.step_index] : null
  const statusColor = status ? DIFF_COLORS[status] : null
  ctx.save()
  ctx.globalAlpha = node.inherited ? 0.5 : 1

  ctx.fillStyle = colors.nodeBg
  roundRect(ctx, r.x, r.y, r.w, r.h, 8)
  ctx.fill()

  ctx.lineWidth = selected ? 2.5 : 1
  ctx.strokeStyle = hasErr
    ? colors.error
    : selected
      ? colors.selected
      : statusColor || color
  ctx.setLineDash(node.inherited ? [4, 4] : [])
  roundRect(ctx, r.x, r.y, r.w, r.h, 8)
  ctx.stroke()
  ctx.setLineDash([])

  ctx.fillStyle = color
  roundRect(ctx, r.x + 8, r.y + 8, 52, 18, 4)
  ctx.fill()
  ctx.fillStyle = '#0b1020'
  ctx.font = 'bold 11px ui-monospace, Consolas, monospace'
  ctx.textBaseline = 'middle'
  ctx.fillText(kindLabel(node.kind), r.x + 12, r.y + 17)

  ctx.fillStyle = colors.nodeTitle
  ctx.font = '12px ui-monospace, Consolas, monospace'
  const title = `#${node.step_index}${node.inherited ? ' ↺' : ''} · ${node.agent_id || ''}`
  ctx.fillText(title, r.x + 68, r.y + 17)

  ctx.fillStyle = node.output == null ? '#64748b' : '#e2e8f0'
  ctx.font = '11px ui-monospace, Consolas, monospace'
  ctx.fillText(outputPreview(node, 42), r.x + 10, r.y + 43)
  ctx.restore()
}

export default function ChainCanvas({
  points,
  selectedId,
  onSelect,
  diffStatus,
  pausedStep,
}) {
  const canvasRef = useRef(null)
  const wrapRef = useRef(null)
  const [hover, setHover] = useState(null)
  const layout = useMemo(() => computeLayout(points), [points])
  const layoutRef = useRef(layout)
  layoutRef.current = layout

  // 主题切换 → 强制重绘(绘制色来自 CSS 变量)
  const [themeTick, setThemeTick] = useState(0)
  useEffect(() => {
    const onTheme = () => setThemeTick((t) => t + 1)
    window.addEventListener('ai-theme', onTheme)
    return () => window.removeEventListener('ai-theme', onTheme)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.round(layout.width * dpr))
    canvas.height = Math.max(1, Math.round(layout.height * dpr))
    canvas.style.width = `${layout.width}px`
    canvas.style.height = `${layout.height}px`
    const ctx = canvas.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, layout.width, layout.height)
    const colors = themeColors()
    drawEdges(ctx, layout.edges, colors)
    for (const node of layout.nodes) {
      drawNode(ctx, node, {
        selected: node.id === selectedId,
        diffStatus,
        colors,
        paused: pausedStep != null && node.step_index === pausedStep,
      })
    }
  }, [layout, selectedId, diffStatus, pausedStep, themeTick])

  const hitTest = (e) => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const nodes = layoutRef.current.nodes
    for (let i = nodes.length - 1; i >= 0; i--) {
      const r = nodes[i].rect
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
        return nodes[i]
      }
    }
    return null
  }

  const tooltipStyle = hover
    ? (() => {
        const wr = wrapRef.current
          ? wrapRef.current.getBoundingClientRect()
          : { left: 0, top: 0, width: 0 }
        const left = hover.x - wr.left + 14
        const top = hover.y - wr.top - 8
        const maxLeft = Math.max(0, wr.width - 300)
        return { left: Math.min(left, maxLeft), top }
      })()
    : {}

  return (
    <div className="chain-canvas" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        onMouseMove={(e) => {
          const n = hitTest(e)
          setHover(n ? { node: n, x: e.clientX, y: e.clientY } : null)
        }}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const n = hitTest(e)
          if (n && onSelect) onSelect(n)
        }}
      />
      {hover && (
        <div className="tooltip" style={tooltipStyle}>
          <b>
            {kindLabel(hover.node.kind)} #{hover.node.step_index}
            {hover.node.inherited ? ' · 共享前缀' : ''}
          </b>
          <span>{hover.node.agent_id}</span>
          <pre>{outputPreview(hover.node, 260)}</pre>
        </div>
      )}
    </div>
  )
}
