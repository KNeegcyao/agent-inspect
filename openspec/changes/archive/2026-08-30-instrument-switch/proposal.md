# instrument-switch

## Why

协议文档早有承诺:"`agent_inspect.start()` 一次调用统一接受记录粒度与**插桩模块开关**"——但 `start()` 实际只接受 db_path/port 等运行参数,**没有任何按模块启停插桩的入口**。当前只要装了 LangChain/OpenAI 就全量包装,用户没有"只要 OpenAI、别动 LangChain"的控制权;对不使用某框架的进程,无谓的包装还引入潜在干扰面。

本 change 补上:`start(instrument={...})` 按模块开关,默认全启用(零破坏)。

## What Changes

- **`session.py`**:`Session.__init__` / `start()` 增 `instrument: Optional[dict] = None`(键 `langchain` / `openai`,值布尔,缺省 True);仅构造并安装启用的 patcher,停用的完全不构造(`_patchers` 亦不含)。
- **spec**:`interception` 能力新增「插桩模块开关」requirement(3 场景)。
- **测试**:单测——默认全启用;指定仅启用其一(`_patchers` 只含该模块,另一框架的包装入口未被替换);未知键忽略或可观测(选择:忽略,向后兼容)。

## Out of scope

- 运行中动态启停(启用即定,stop 卸载);Node SDK 的同名开关(它的插桩面只有 OpenAI 一项,`installOpenAIInterceptor` 已天然可开关);环境变量形态的开关。

## Criteria

- `start(instrument={"langchain": False})`:OpenAI 照常插桩,LangChain 的包装入口保持原样(未被替换);
- 默认(不传 instrument)行为与现状完全一致(全启用);
- 全量测试零回归。
