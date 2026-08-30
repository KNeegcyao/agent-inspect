# python-streaming-instrumentation

## Why

OpenAI SDK 的流式调用(`stream: true`)是生产 Agent 的主流形态(首 token 延迟、打字机体验),但当前插桩对它完全未处理:流对象会被粗糙地 shape(拿不到有效输出),**调试器对最重要的生产路径视而不见**。这是记录覆盖面的实洞。

流式的本质挑战:决策点的"输出"要在流耗尽后才完整,而用户代码边收边用。方案:**透传 + 旁路累积**——把真实流包一层,chunk 原样交给用户,累积器同步拼接 content / tool_calls,流结束时把累积结果按既有契约 shape 并登记决策点。回放与 Fork 语义:命中的记录回放为**合成流**(单块 delta,兼容 `chunk.choices[0].delta.content` 读取);注入修改 / dry_run / 沙箱 / Live 咨询在流开始前决策(与既有语义一致)。

范围克制:兼容 `for chunk in stream` 与 `async for`;`stream.close()` 提前关闭时按已累积内容登记;不逐 chunk 建模(只累积);`stream_options.include_usage` 的 usage 随最后块捕获。

## What Changes

- **`interceptor.py`(新增 `route_stream` / `aroute_stream`)**:流式决策点路由——游标/步骤/因果边/咨询(Live)/模式路由与既有三态一致;差异只在"native"是流对象:
  - replay / fork 前缀命中:回放为合成流(不真调,needsRecord=false);
  - fork 后缀:输出注入 → 合成流(注入值);dry_run / 沙箱命中 → 合成空流并打 meta 标记;
  - record / 真调:`_TeeStream` 包装真实流,chunk 透传 + 累积,耗尽时 shape 累积结果并登记落盘;
  - `_SyntheticStream`:单块合成流(delta.content/tool_calls/finish_reason)。
- **`openai_patcher.py`**:`_create` / `_acreate` 检测 `kwargs.get("stream")` → 走 `route_stream / aroute_stream`;输入契约不变(params 含 stream 标记)。
- **spec**:`interception` 能力新增「流式调用插桩」requirement(3 场景)。
- **测试**:本地 SSE mock 端点——记录(透传 chunk + 累积落盘)、回放(合成流、零真实请求)、异步流式记录;非流式路径零回归。

## Out of scope

- 逐 chunk 建模入存储(只存累积后的完整输出);流的 usage 仅在 `stream_options.include_usage` 开启时捕获;其它 SDK 的流式(TS 侧维持透传);Live 咨询对流的"暂停在中间块"(暂停只发生在流开始前)。

## Criteria

- `stream: true` 的调用:用户收到的 chunk 序列与不插桩时一致;流耗尽后,决策点以累积的完整输出(内容/工具调用)落盘;
- 回放命中的流式决策点:用户迭代合成流可读到记录的完整内容,不发起真实调用;
- 注入 / dry_run / 沙箱对流式后缀的语义与非流式一致;非流式路径零回归。
