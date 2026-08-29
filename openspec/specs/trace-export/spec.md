# trace-export Specification

## Purpose
把本系统的一条 trace(自录或导入)的决策链导出为遵循既定开源观测语义约定的 span 导出 JSON,与导入能力互为逆操作:导出的文件可被导入端原样消费,重建出内容一致的链路。导出是只读计算,不产生任何写入、不改变被导出 trace。

## Requirements

### Requirement: 导出链路为外部 span 导出

系统 SHALL 支持把一条 trace 的决策链导出为一份 span 导出 JSON,每个决策点映射为一个对应类型的 span,保持顺序、完整输入输出与因果关系。

#### Scenario: 决策点映射为 span

- **WHEN** 对一条含 LLM 与工具决策点的 trace 发起导出
- **THEN** 导出结果为合法的 span 导出 JSON:每个决策点对应一个 span,顺序与链路一致;LLM 决策点的完整输入(消息列表、模型、参数)与输出(内容、工具调用)及工具决策点的工具名、参数、返回值均可从对应 span 属性读回

#### Scenario: 空链导出

- **WHEN** 对一条尚无决策点的 trace 发起导出
- **THEN** 返回不含任何 span 的合法导出 JSON,且不产生任何写入

### Requirement: 导出与导入往返等价

系统 SHALL 保证导出产物可被导入端消费并重建内容等价的链路。

#### Scenario: 导出后再导入内容一致

- **WHEN** 把一份由本系统导出的 span 导出 JSON 再次导入
- **THEN** 新 trace 的决策点类型、顺序、输入与输出与被导出链路逐一一致(标识符与来源标记允许不同)

### Requirement: 导出入口可观测

系统 SHALL 提供面板与 API 的导出入口,并对异常请求给出可观测原因。

#### Scenario: 面板一键导出

- **WHEN** 在面板中对一条 trace 触发导出
- **THEN** 获得一份可下载的 span 导出 JSON 文件

#### Scenario: trace 不存在拒绝

- **WHEN** 对不存在的 trace 标识发起导出
- **THEN** 返回 404 与可观测原因
