# panel-theme-toggle Tasks

## 1. OpenSpec 文档

- [ ] 1.1 `proposal.md` / `design.md`:主题切换的 why / 浅色调色板 / 画布变量化
- [ ] 1.2 `specs/trace-ui/spec.md` delta:「面板主题切换」1 requirement 共 3 场景

## 2. 实现

- [ ] 2.1 `styles.css`:浅色调色板(`[data-theme="light"]`)+ 画布专用变量(深浅两套)
- [ ] 2.2 `ChainCanvas.jsx`:绘制色读 CSS 变量(兜底原值)+ 监听主题事件重绘
- [ ] 2.3 `App.jsx`:主题状态(localStorage 持久化,默认深色)+ 切换按钮 + 派发主题事件

## 3. 验证与发布

- [ ] 3.1 `npm run build` 通过;全量 pytest 零回归
- [ ] 3.2 浏览器实测:切换即时生效(画布重绘)/ 刷新保持 / 默认深色;核心视图两主题可读
- [ ] 3.3 `openspec validate --all` 通过;`openspec archive panel-theme-toggle`;commit + push
