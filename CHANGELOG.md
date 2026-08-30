# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 语义;版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-08-30

首个可发布版本:AI Agent 的交互式调试器(Python + Node 双生态)。

### 新增

- **Python SDK**(`pip install agent-inspect`):一行 `agent_inspect.start()`,自动插桩 LangChain 与 OpenAI SDK,内嵌面板自启。
- **Counterfactual Fork(旗舰)**:从任意决策点分叉——前缀用记录输出确定性回放(不真调),注入修改后真实重跑后缀;支持 prompt/工具返回/参数注入与只读预览(`dry_run`)。
- **Fork 副作用沙箱**:按决策点类型(LLM / 工具)独立配置 `allow / dry-run / block`,隔离真实副作用。
- **Live 调试(Mode C)**:附加运行中的 Agent,条件断点、暂停 / 单步 / 继续、暂停点改输入。
- **分支并排 diff + 采纳差异为 Fork**:按步骤对齐(same/diff/only_left/only_right)、字段级明细、跨 trace 对比、差异一键映射为 Fork 修改。
- **跨进程追踪**:子进程经 `AGENT_INSPECT_PARENT_TRACE` 环境变量挂到父 trace。
- **OpenInference 互操作**:导入外部 span 导出(OTLP JSON 信封 / 扁平列表)为可 Fork 链路;导出任意 trace 为同格式(往返等价);推送链路到任意 OTLP/HTTP 收集端点(零依赖)。
- **JavaScript / Node SDK**(`sdks/node/`,npm `agent-inspect-node`):一行启用 + OpenAI Node SDK 自动插桩 + record/fork 同款引擎,零改动复用同一份面板(运行时零依赖)。
- **面板(React 单页)**:决策链画布、完整 prompt 检查、Fork 表单、并排对比、trace 导入 / 导出 / 推送。
- **CI**:GitHub Actions 双语言矩阵(Python 3.11/3.12 × pytest + openspec 校验;Node 20/22 × SDK 测试;web 构建)。

### 行为约定

- 面板随包分发(pip wheel 内置 `agent_inspect/panel`;npm 包内置 `panel/`),安装即得完整面板,无需前端构建。
- 拦截零成本默认关闭;启用后已完成的决策点崩溃不丢;多分支并发写入串行落盘。
- trace 列表按开始时间倒序,同时钟平局按插入序(确定)。
- 调试释放指令(step/continue/modify)绑定发起时的暂停点,重复投递不误放后续暂停点。

[0.1.0]: https://github.com/KNeegcyao/agent-inspect/releases/tag/v0.1.0
