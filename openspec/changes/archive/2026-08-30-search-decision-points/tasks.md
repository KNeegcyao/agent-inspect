# search-decision-points Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:搜索的 why / 匹配语义 / 范围
- [x] 1.2 `specs/trace-search/spec.md` delta:2 requirement(内容搜索 / 搜索入口)共 5 场景

## 2. 后端

- [x] 2.1 新建 `agent_inspect/search.py`:`search_trace`(全分支遍历、解析后序列化匹配、snippet 合成、排序);单测(输入/输出命中、大小写、无命中、排序、截断压行)
- [x] 2.2 `GET /api/traces/{trace_id}/search?q=`:200 / 404 / 422

## 3. UI

- [x] 3.1 api.js `searchTrace`;App.jsx 工具栏搜索框(防抖)+ 结果浮层(高亮片段)+ 点击定位(切分支 + 选中点)+ Esc/清空收起
- [x] 3.2 浮层与命中高亮样式

## 4. 测试与回归

- [x] 4.1 e2e:搜索命中(大小写不敏感标注 output)/ 404 / 422
- [x] 4.2 全量 pytest 通过,零回归;`npm run build` 通过

## 5. 验证与发布

- [x] 5.1 `openspec validate --all` 通过
- [x] 5.2 README 补搜索一句;`openspec/archive search-decision-points`;commit + push
