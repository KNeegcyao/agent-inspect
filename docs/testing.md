# Agent-Inspect 测试策略

> 怎么测:三测怎么搭、怎么免真 token、69 个 spec scenario 怎么映射、覆盖率与回归基线。
> 行为验收以 [openspec/](../openspec/) 为准(每个 `#### Scenario:` 即一条判据);本文是"怎么把它跑出来"。

## 1. 三层测试

| 层 | 目录 | 范围 | 速度 | 是否触真 LLM |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | interceptor 路由三态、recorder 增量/去重、fork 引擎前缀/后缀、contextvars 传播 | <1s/文件 | 否,全 mock |
| **Integration** | `tests/integration/` | LangChain ReAct demo 全链、OpenAI 兼容 SDK 回放、SQLite store 读写、一年 trace 端到端 | 秒级 | 否,FakeLLM |
| **E2E** | `tests/e2e/` | `agent_inspect.start()` → 自动开面 → 发起 fork → 看到新分支 | 十秒级 | 否(FakeLLM) |

**铁律:CI 不烧真 token、不发真实网络。** 一切 LLM 行经 FakeLLM(伪造的确定响应)。

## 2. Unit 测试重点(对应 spec)

### Interceptor 路由(三态) — `interception`
- replay 用 recorded output、不真调 → spec `interception.Replay 模式不真调`
- replay 无记录输出时退回真调 → `Replay 缺记录输出时退回真调`
- fork 前缀(step≤起点)用 recorded → `Fork 前缀用记录`
- fork 后缀(step>起点)真调 → `Fork 后缀真调`
- dry_run=True 时后缀也不真调 → `fork.只读预览档`
- 调用抛错仍登记 dp 不中断 → `interception.调用失败登记`
- 关闭后零开销原样跑 → `非侵入启停.关闭零回归`
- 异步决策点同属 trace/branch → `执行上下文传播.异步决策点同属`

### Recorder — `recording`
- 大对象相同 → 存一份、引用关联 → `大对象去重存储.相同输出去重`
- 大对象不同 → 各自留存 → `差异输出各自留存`
- 增量:共享前缀只存一次,单点回放仍能还原全量 → `增量上下文快照` 两场景
- dev/prod 两档:prod 大对象 hash 不存全文 → `可配记录粒度.轻量记录档`
- 因果边落库 → `因果关系可追溯`
- **崩溃不丢已完成者** → `异常中止前已登记者不丢`(测试:中途 raise,断言已登记的 dp 仍在 store)

### Fork 引擎 — `fork`
- 从决策点发起新 branch,parent/origin 正确 → `从决策点发起分支`
- **根决策点 fork**(前缀为空) → `在根决策点 Fork`
- **空 trace fork 被拒** + 可观测原因 → `空链 Fork`
- **嵌套 fork**(fork 一个 fork 产物,前缀沿用该分支记录回放) → `嵌套 Fork`
- 前缀不发真调,后缀真调 → `前缀确定性回放`+`后缀真实执行`
- 修改 prompt / 工具返回 / 参数 各自生效 → `注入修改` 三场景
- 分支枚举含 origin(record|fork),原始分支标"记录" → `分支图可枚举与并排`
- 多分支并发写入不损坏 → `并发分支写入安全`(并发跑两条后缀,断言都可读回)

### Local runtime — `local-runtime`
- 一次调用同时起拦截+面板 → `一次调用启用`
- 无头/CI 降级打印 URL 不报错 → `无头环境降级`(测 `autostart_browser=False` + 无浏览器时)
- 端口占用自动择可用 → `端口冲突自适应`
- SATMP 决策点实时推 → `实时双向消息.决策点实时推送`(前后不发 SST)
- 进程退出后历史可读 → `进程退出后历史留存`
- trace done/aborted 三态 + 筛选查询 → `Trace 生命周期`

### Trace UI — `trace-ui`
- 决策链路树渲染 + 多分支分叉可视 → `单条 trace 决策链路视图`
- 决策点全文 prompt/输入输出检查 → `决策点细节检查`
- 面板发起 fork + 修改生效 → `Fork 交互入口`
- 原始 vs fork 视觉区分 + 并排对照 → `分支并排区分`
- 实时追加 + fork 后续回流 → `执行中实时追加`
- 完成/空链终态呈现 → `Trace 终态呈现`
- UI 测试用 **React Testing Library + 快照**,不依赖真执行。

## 3. FakeLLM(免 token 的关键设施)

自建一个确定的伪 LLM(可按脚本编排响应序列),LangChain 与 OpenAI 兼容 SDK 测试均经它:
```python
# tests/conftest.py 里全局注入
class FakeLLM:                       # 实现 LangChain BaseChatModel 与 OpenAI 兼容接口最小集
    def __init__(self, scripted): self.responses = iter(scripted)
    def invoke(self, messages, **kw): return next(self.responses)
```
- integration/e2e 的"真调"其实调 FakeLLM,确定性、免费、CI 安全。
- fork 测试靠它验证"后缀真调吃的是新响应、前缀吃的是 recorded"。

## 4. scenario → 测试映射(思路)

不强制 1:1,但**每条 spec `#### Scenario:` 必须有至少一处测试覆盖**:
- 多数 Scenario 直接译成 1 个 test 函数(用上面 §2 的命名对应)。
- 关键边界(根 fork / 空 fork / 嵌套 fork / 崩溃不丢 / 并发写入安全)各一个独立测试,fixture 显式构造该边界。
- UI scenario 用组件单测 + 关键路径 e2e,不追求逐像素。

> 建议在测试函数 docstring 里回链 scenario 名(如 `# spec: fork.嵌套 Fork`),便于回归时定位 spec。

## 5. 覆盖率与门槛

- **最低 80%**(全局);interceptor / recorder / fork 引擎三件**不低于 90%**(核心路径)。
- 覆盖率工具 `coverage`(pytest-cov);`pytest --cov` 输出。
- 分支覆盖(branch)开启,不只看行。

## 6. 回归基线(零侵入验收)

硬性:`interception.关闭零回归`。维护一条回归测试:
- 一个**现成 LangChain ReAct 用例**(跑通的真实示例,在 `tests/integration/fixtures/`)。
- 在"不开 `agent_inspect.start()`"时跑 → 行为/输出与不加本 repo 时**一致**(断言关键输出、调用次数)。
- 在"开了又关(`session.stop()`)"时跑 → 同样一致。
- 这条测试保护"插桩不污染被测框架"不被破坏。

## 7. 测试文件布局(对应架构)

```
tests/
├── conftest.py                        # FakeLLM、store fixture、mode_ctx fixture
├── unit/
│   ├── test_interceptor_router.py     # 路由三态 + dry_run
│   ├── test_recorder_dedup.py         # 去重
│   ├── test_recorder_context_snap.py  # 增量快照
│   ├── test_fork_engine.py            # 前缀/后缀/根/空/嵌套
│   └── test_contextvars_propagation.py# 异步同属
├── integration/
│   ├── fixtures/                      # 现成 LangChain ReAct 用例(回归基线)
│   ├── test_langchain_react_full.py
│   ├── test_openai_compat_replay.py
│   ├── test_store_persistence.py      # 重启可读
│   └── test_concurrent_branches.py    # 并发写入安全
└── e2e/
    ├── test_one_line_start.py          # start→面板就绪
    └── test_fork_one_cut.py           # start→fork→看到分支(旗舰 demo 自动化)
```

## 8. 跑法

```bash
python -m pip install -e ".[dev]"
pytest -q                              # 全绿才能提交
pytest --cov=agent_inspect --cov-branch
pytest tests/e2e                       # 仅 e2e
# 规格侧
openspec validate --all                # 1 passed
```

CI(远期)顺序:`openspec validate` → `pytest` → `cd ui && npm ci && npm run build` → UI 测试。任一红则阻断。
