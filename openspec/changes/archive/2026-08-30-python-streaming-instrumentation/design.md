# python-streaming-instrumentation Design

## 概述

流式插桩 = 既有三态路由 + "native 是流"的适配层。透传与累积并行:`_TeeStream`/`_AsyncTeeStream` 包住真实流,chunk 原样交付,耗尽时把累积结果按契约 shape 并走既有登记路径(`finalize` 等价物)。回放命中返回 `_SyntheticStream`(单块 delta,兼容 `chunk.choices[0].delta.content`)。

## 1. 路由(`interceptor.py` 新增)

```python
def route_stream(self, *, kind, agent_id, input_context, start_call, reconstruct, make_modified_call=None):
```

- 游标/步骤/dp 构建/因果边/Live 咨询(命中 → 应用替换 start_call)与 `sroute` 一致;
- 模式路由:
  - replay / fork 前缀命中记录 → `_SyntheticStream(reconstruct(rec))`,needsRecord=False;
  - fork 后缀:output 注入 → `_SyntheticStream(注入值)` + finalize;input 修改 → 换 start_call;dryRun / 沙箱命中 → `_SyntheticStream(None)`(空流)+ finalize(meta 标记);
  - 真调:`_TeeStream(start_call(), on_done=...)`;
- `aroute_stream`:同构(async 版,`_AsyncTeeStream` 支持 `async for`)。

## 2. 累积与 shape

- `_StreamAcc`:content 列表拼接;tool_calls 按 index 聚合(id/name 首见,args 片段拼接);id/model 首见;usage 取最后非空块;
- `shape_stream(acc)` → `{"content", "tool_calls", "id", "model", "usage"?}`(与 `_shape_response` 契约一致,reconstruct 可直接回放);
- `_TeeStream.__next__`:透传 chunk → absorb;StopIteration 时 `on_done(acc)`(shape + meta(latency/ts)+ 落盘 + 事件 + `cursor.last_dp_id`)再抛出;提前 `close()` 亦按已累积内容登记(崩溃不丢已完成者)。

## 3. 插桩(`openai_patcher.py`)

`_create` / `_acreate` 开头:`if kwargs.get("stream"): return interceptor.route_stream / aroute_stream(...)`——输入契约不变(messages/model/params 含 stream 标记);start_call = `orig_create(self, **kwargs)`。

## 4. 合成流(`_SyntheticStream`)

可迭代单块:`chunk.choices[0].delta.{content, tool_calls}`、`finish_reason="stop"`;`close()` 可用。覆盖用户侧最常见的消费路径(拼接 delta.content / 检查 finish_reason)。

## 5. 测试(`tests/integration/test_openai_stream_e2e.py` + 单测)

- 本地 SSE mock(http.server):两内容块 + finish + [DONE];
- 记录:迭代收齐 "HE"/"LLO",落盘 content="HELLO",输入可查;
- 回放:fork from_step=1 消费(step0 合成流零真实请求,内容与记录一致;step1 真调命中 mock);
- 异步记录(`astream` 路径 async for);
- 非流式既有测试零回归(openai e2e/单测不动)。

## 数据流

```
create(stream=True) → route_stream: dp 构建 → Live 咨询 → 模式路由
  真调: _TeeStream(chunk 透传 + 累积) → 耗尽 → shape_stream → 落盘/事件
  回放命中: _SyntheticStream(记录输出) → 零真调
  dryRun/沙箱: _SyntheticStream(空) → meta 标记
```
