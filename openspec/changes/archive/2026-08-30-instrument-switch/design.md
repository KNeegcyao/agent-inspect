# instrument-switch Design

## 概述

`Session.__init__` / `start()` 增 `instrument: Optional[dict] = None`(键 `langchain` / `openai`,布尔,缺省 True)。仅构造并安装启用的 patcher;停用的完全不进 `_patchers`(stop 时也无从卸载,天然零改动)。

## 1. 实现(`session.py`)

```python
instrument = instrument or {}
patchers_cls = []
if instrument.get("langchain", True):
    patchers_cls.append(LangChainPatcher)
if instrument.get("openai", True):
    patchers_cls.append(OpenAIPatcher)
self._patchers = [cls() for cls in patchers_cls]
for p in self._patchers:
    p.install(self.interceptor)
```

未知键忽略(向后兼容,宽松处理)。`start(**kwargs)` 透传即得。

## 2. 测试(`tests/unit/test_instrument_switch.py`)

- 默认:`_patchers` 含两类实例;
- `{"langchain": False}`:仅 OpenAIPatcher;且 `BaseChatModel.invoke` 保持原函数(LangChainPatcher 未包装——以 patcher 实例缺失为充分条件,另断言 `_patchers` 中无 LangChainPatcher);
- `{"openai": False}`:仅 LangChainPatcher;
- 混合 + 未知键:同默认;
- Session.stop 后包装卸载(既有行为不回归)。
