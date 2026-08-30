# trace-stats-summary Design

## 概述

纯前端聚合,零后端/零 schema 改动。统计 = 对当前主分支链路(`activeChain`)的纯函数归约;面板 rel-bar 以 chip 展示,无数据不渲染。Node SDK 复用同一面板自动获得同能力。

## 1. 聚合(`web/src/chain.js`)

```js
export function summarizeChain(points) {
  let latencyMs = null, tokens = null, counted = false
  for (const p of points) {
    const lat = p.meta?.latency_ms
    if (typeof lat === 'number') { latencyMs = (latencyMs ?? 0) + lat; counted = true }
    const usage = p.output?.usage?.total_tokens
    const metaIn = p.meta?.tokens_in, metaOut = p.meta?.tokens_out
    let t = null
    if (typeof usage === 'number') t = usage
    else if (typeof metaIn === 'number' || typeof metaOut === 'number') t = (metaIn ?? 0) + (metaOut ?? 0)
    if (t != null) { tokens = (tokens ?? 0) + t; counted = true }
  }
  return counted ? { latencyMs, tokens } : null
}
```

要点:耗时与 token 分别独立判定"有数据"(只有耗时的链不显示 tokens chip);usage 优先、meta 回退;非数值不计。

## 2. 展示(`web/src/App.jsx`)

- `chainStats = useMemo(() => summarizeChain(activeChain), [activeChain])`;
- rel-bar 追加:`{chainStats?.latencyMs != null && <span className="rel-chip">Σ 耗时 {fmtLatencyValue(chainStats.latencyMs)}</span>}` 与 `{chainStats?.tokens != null && <span className="rel-chip">Σ {chainStats.tokens.toLocaleString()} tokens</span>}`;
- `fmtLatencyValue`:≥1000ms → `x.xxs`,否则 `…ms`(复用 fmtLatency 语义,输入为合计值)。

## 3. 样式

复用 `.rel-chip`;不新增样式。

## 4. 验证

- Node 示例链(mock 端点输出带 `usage.total_tokens=2`)→ 浏览器实测:chips 显示 `Σ 耗时 …` 与 `Σ 4 tokens`(两步 × 2);
- Python 脚本模型链(无 usage/meta tokens)→ 仅显示耗时 chip;
- `npm run build` + 全量 pytest 零回归。
