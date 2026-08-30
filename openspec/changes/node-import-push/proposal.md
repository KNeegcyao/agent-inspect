# node-import-push

## Why

Node 面板的契约子集里,「导入」和「推送」两个按钮至今是 404——这是 js-sdk 声明的契约子集里最后两个报错入口。检索/导出已在 Node 侧就位,补上导入与推送后:

- Node Agent 的链路可从外部 span 导出文件导入并 Fork(与 Python 同语义);
- Node 链路可推送到任意收集端点;
- **面板不再有报错按钮**——双生态契约子集从此完整。

移植成本低:导入器/推送器在 Python 侧均已实现且带完整测试,TS 移植是同构翻译(Node 端存储全量内联,导入无需增量快照处理)。

## What Changes

- **`sdks/node/src/importer.ts`(新增)**:与 Python `importer.py` 同语义——OTLP JSON 信封与扁平 span 列表两形态;`openinference.span.kind` 识别(LLM/TOOL,其余忽略并计数);属性拍平 + JSON 字符串二次解析;稳定排序 + DFS 定步序;线性因果边;LLM 输出映射 `{content, tool_calls}`、工具映射 `{tool, args}`/`{result}`;空映射拒绝;经既有 store 落库(全量内联,与 Node 录制同构)。
- **`sdks/node/src/pusher.ts`(新增)**:复用 `exporter.ts` 信封,包装推送协议载荷(scope 声明 + span kind),`fetch` POST(超时经 AbortSignal);成功返回送达统计,失败抛可观测错误。
- **`server.ts`**:`POST /api/traces/import`(422 不落库)、`POST /api/traces/{id}/push`(404/502)。
- **spec**:`js-sdk` 能力新增「导入与推送」requirement(3 场景)。
- **测试**:导入映射单测(两形态/逐字段/因果/忽略计数/拒绝)、推送单测(mock 收集端)、HTTP e2e(导入 → 查看 → Fork;推送 → mock 端点收到与导出一致的载荷)。

## Out of scope

- OTLP/gRPC 二进制、鉴权 header、批量操作;Node 端 `meta` 沙箱标记等派生信息的导出(与 Python 一致仅导核心链路)。

## Criteria

- 合法 span 导出 JSON 经 `POST /api/traces/import` 生成与 Python 侧同构的 trace(LLM/TOOL 决策点、顺序、输入输出、因果边),非法 422 不落库;
- `POST /api/traces/{id}/push` 将链路送达用户端点(载荷与导出映射一致),成功回报送达数,失败 502 可观测;
- 面板导入/推送按钮在 Node 面板真实可用;全量测试零回归。
