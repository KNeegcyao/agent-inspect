# python-streaming-instrumentation Tasks

## 1. OpenSpec 文档

- [x] 1.1 `proposal.md` / `design.md`:流式插桩的 why / 透传+累积方案 / 回放合成流
- [x] 1.2 `specs/interception/spec.md` delta:「流式调用插桩」1 requirement 共 3 场景

## 2. 实现

- [x] 2.1 `interceptor.py`:`_StreamAcc` / `shape_stream` / `_TeeStream` / `_AsyncTeeStream` / `_SyntheticStream` / `route_stream` / `aroute_stream`
- [x] 2.2 `openai_patcher.py`:stream 检测分流(同步/异步)

## 3. 测试与回归

- [x] 3.1 SSE mock 记录测试(透传一致 + 累积落盘)
- [x] 3.2 回放合成流测试(零真实请求)
- [x] 3.3 异步流式记录测试
- [x] 3.4 全量 pytest 零回归(含 openai 非流式既有测试)

## 4. 验证与发布

- [x] 4.1 `openspec validate --all` 通过
- [x] 4.2 README 插桩说明补流式一句;`openspec archive python-streaming-instrumentation`;commit + push
