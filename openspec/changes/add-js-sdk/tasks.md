# add-js-sdk Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:JS 运行时 SDK 的 why / 切片边界 / 存储与插桩选型
- [x] 1.2 `specs/js-sdk/spec.md` delta:4 requirement(一行启用 / 自动拦截 / Fork / 面板契约一致)共 9 场景

## 2. 核心引擎(sdks/node)

- [x] 2.1 包脚手架:package.json(name/type/engines/scripts)、tsconfig(strict/NodeNext)、tsc 构建通过
- [x] 2.2 models + store:单文件 JSON、原子写、写队列串行、查询子集;单测(读写/并发串行/lastStepBefore)
- [x] 2.3 context(AsyncLocalStorage 游标)+ fork 控制器(校验:空链/越界/归属,不落库);单测
- [x] 2.4 interceptor 三态路由 + 注入路径补丁(嵌套/数组);单测(真调/回放/注入/dryRun)

## 3. 插桩与服务

- [ ] 3.1 openai 拦截器:包装 Chat.Completions.prototype.create,输入/输出契约形态 + reconstruct;mock 端点单测(记录/回放);stream 放行;缺包跳过
- [ ] 3.2 server:REST 子集 + SSE + 错误契约(404/422)+ 静态面板;集成测试
- [ ] 3.3 diff + adopt 预览移植;导出信封;单测
- [ ] 3.4 session/start 装配 + 自动开浏览器 + 优雅 stop;示例脚本 quickstart(离线 mock)

## 4. e2e 与回归

- [ ] 4.1 e2e:启用 → 两步链 → REST 发起 Fork(注入消息)→ 再执行 → 新分支 3 点、前缀回放不真调、注入生效
- [ ] 4.2 全量 node:test 通过;Python pytest 全量零回归;web build 零回归
- [ ] 4.3 面板连通性:JS 服务下链路/详情/Fork 表单/对比视图可用(契约子集足够支撑面板)

## 5. 验证与发布

- [ ] 5.1 `openspec validate --all` 通过
- [ ] 5.2 README 增 JS SDK 一节 + sdks/node/README;`openspec/specs/README.md` 能力清单随 archive 更新
- [ ] 5.3 `openspec archive add-js-sdk --yes`;commit + push
