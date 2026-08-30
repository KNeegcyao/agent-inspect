# panel-theme-toggle Design

## 概述

以既有 CSS 变量骨架为基底:`[data-theme="light"]` 覆盖 11 个界面变量 + 新增画布专用变量;Canvas 绘制改为绘制时 `getComputedStyle` 读变量(带原值兜底)并监听主题事件重绘;切换入口持久化到 localStorage(`ai-theme`),默认深色。

## 1. 调色板(`styles.css`)

```css
:root { ...现有 11 项... ;
  /* 画布绘制色(Canvas 不吃 CSS 变量,绘制时读取) */
  --canvas-node-bg: #121a2c; --canvas-node-title: #cbd5e1;
  --canvas-node-text: #e2e8f0; --canvas-node-muted: #64748b;
  --canvas-edge: #334155;
}
[data-theme="light"] {
  --bg: #f3f5f9; --panel: #ffffff; --panel-2: #f7f9fc; --border: #d8e0ec;
  --text: #1c2536; --muted: #64748b;
  --accent: #2563eb; --accent-2: #0369a1; --fork: #b45309;
  --danger: #dc2626; --ok: #059669;
  --canvas-node-bg: #ffffff; --canvas-node-title: #1c2536;
  --canvas-node-text: #334155; --canvas-node-muted: #94a3b8;
  --canvas-edge: #cbd5e1;
}
```

徽标/状态色(accent 系、kind 色、diff 状态色)保持原值——两套主题下均可读;「彩底深字」类(#0b1020)保留(彩底上深字两主题通用)。

## 2. 画布(`ChainCanvas.jsx`)

- `themeColors()`:一次性 `getComputedStyle(document.documentElement)` 读取上述画布变量,兜底原硬编码值;
- `drawNode/drawEdges` 使用 `themeColors()`;KIND_COLORS 与 DIFF_COLORS 保持(强调色双主题可读);
- `useEffect` 订阅 `window.addEventListener('ai-theme', ...)` → 计数器 state 触发重绘;卸载时移除。

## 3. 切换入口(`App.jsx`)

- `const [theme, setTheme] = useState(() => localStorage.getItem('ai-theme') || 'dark')`;
- `useEffect([theme])`:写 `document.documentElement.dataset.theme` + localStorage,派发 `ai-theme` 事件;
- 侧栏头部(「实时」徽标旁)按钮:深色显示「☀️ 浅色」、浅色显示「🌙 深色」(动作语义:切到目标主题);样式复用 chip 观感(`.theme-toggle`)。

## 4. 验证

浏览器实测:切换即时生效(列表/链路画布/详情/对比四视图过一遍)、刷新保持、清 localStorage 恢复深色;`npm run build` + 全量 pytest 零回归。
