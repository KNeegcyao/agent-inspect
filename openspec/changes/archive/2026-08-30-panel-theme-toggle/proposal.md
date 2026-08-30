# panel-theme-toggle

## Why

面板目前只有深色主题。调试场景里大段 prompt/输出的**长时间阅读**下,不少用户偏好浅色;且主题切换是开发者工具的标配体验(VSCode / Chrome DevTools 都提供)。现有样式已经以 CSS 变量为骨架(`:root` 11 个变量),浅色主题的边际成本很低——主要工作是浅色调色板、画布绘制色变量化(Canvas 不吃 CSS 变量,需绘制时读取并随主题重绘)与偏好持久化。

默认保持深色(既有用户的观感不变);偏好存 localStorage(按面板 origin 隔离)。

## What Changes

- **浅色调色板**:`styles.css` 增加 `[data-theme="light"]` 变量覆盖(bg/panel/border/text/muted 等 11 项);补充画布专用变量(`--canvas-node-bg/title/text/muted`、`--canvas-edge`),深浅各一套。
- **画布随主题重绘**(`ChainCanvas.jsx`):绘制色从硬编码改为绘制时读取 CSS 变量(带原值兜底);监听主题切换事件强制重绘,Canvas 节点/连线配色随主题同步。
- **切换入口**(`App.jsx`):侧栏头部主题切换按钮(🌙/☀️),切换即写 `documentElement.dataset.theme` 并持久化 localStorage(`ai-theme`);加载时恢复偏好;派发主题事件触发画布重绘。
- **spec**:`trace-ui` 能力新增「面板主题切换」requirement(3 场景)。

## Out of scope

- 跟随系统偏好(`prefers-color-scheme`)自动切换(后续可加);第三套主题;画布 kind 徽标配色(dff/diff 状态色)按主题微调(现有强调色两套主题下均可读)。

## Criteria

- 点击切换按钮,面板配色立即在深色/浅色间切换,链路画布同步重绘,全部功能不受影响;
- 切换后重新打开面板,保持上次选择的主题;从未切换时默认深色;
- 全量测试零回归;`npm run build` 通过;两种主题下浏览器实测核心视图(列表/链路/对比/详情)可读。
