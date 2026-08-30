# node-side-effect-sandbox Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:沙箱的 why / 移植语义 / 范围
- [x] 1.2 `specs/js-sdk/spec.md` delta:「JS 运行时副作用沙箱」1 requirement 共 4 场景

## 2. 实现

- [x] 2.1 `fork.ts` sandbox 校验(非法 ForkError 不落库)+ `context.ts` Cursor.sandbox
- [x] 2.2 `interceptor.ts` 策略闸门(dry-run/block 拦截 + meta 标记,优先级与 Python 一致);单测(四场景 + 混合配置)

## 3. 服务与验证

- [x] 3.1 `/api/forks` 透传 sandbox;e2e(meta 标记 + 无真调 + 非法 422)
- [x] 3.2 全量 node:test 零回归;Python pytest 零回归;`npm run build` 通过
- [x] 3.3 `openspec validate --all` 通过;`openspec archive node-side-effect-sandbox`;commit + push
