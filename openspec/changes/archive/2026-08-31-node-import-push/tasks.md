# node-import-push Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:导入/推送的 why / 移植映射 / 范围
- [x] 1.2 `specs/js-sdk/spec.md` delta:「导入与推送」1 requirement 共 2 场景

## 2. 实现

- [x] 2.1 `importer.ts`(两形态/拍平/映射/DFS/拒绝);单测
- [x] 2.2 `pusher.ts`(载荷包装 + fetch 推送);单测(mock 收集端)
- [x] 2.3 `server.ts` 两端点(422/404/502);e2e(HTTP 全链路)

## 3. 验证与发布

- [x] 3.1 全量 node:test 零回归;Python pytest 零回归;`npm run build` 通过
- [x] 3.2 `openspec validate --all` 通过;`openspec archive node-import-push`;commit + push
