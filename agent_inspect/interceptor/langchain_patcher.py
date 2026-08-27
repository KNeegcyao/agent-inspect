"""LangChain 自动插桩。

在「高语义稳定入口」包装(design.md 决策,拒绝全进程 monkeypatch socket):
- LLM 决策点:`BaseChatModel.invoke / ainvoke`
- 工具决策点:`BaseTool.invoke / ainvoke`(覆盖 Tool / StructuredTool / @tool 产物)

langchain 由用户项目自带,不硬绑 runtime deps;未安装时插桩静默跳过。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ..recorder.serializer import Serializer, _jsonable

try:  # 允许在未装 langchain 的环境导入本模块而不报错
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
except Exception:  # noqa: BLE001
    AIMessage = HumanMessage = SystemMessage = ToolMessage = None


def _rebuild_messages(msgs: list) -> list:
    if AIMessage is None:
        return msgs
    out = []
    for d in msgs:
        if not isinstance(d, dict):
            out.append(d)
            continue
        role = d.get("role")
        content = d.get("content")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content, tool_calls=d.get("tool_calls") or []))
        elif role == "tool":
            out.append(ToolMessage(content=content or "", tool_call_id=d.get("tool_call_id") or ""))
        else:
            out.append(HumanMessage(content=content))
    return out


def _reconstruct_llm(out: Optional[dict]):
    if out is None:
        return None
    if AIMessage is None:
        return out
    return AIMessage(content=out.get("content"), tool_calls=out.get("tool_calls") or [])


def _shape_llm(msg) -> dict:
    tc = []
    for c in (getattr(msg, "tool_calls", None) or []):
        tc.append({"name": c.get("name"), "args": c.get("args"), "id": c.get("id")})
    return {"content": msg.content, "tool_calls": tc}


def _llm_meta(msg) -> dict:
    meta: dict = {}
    um = getattr(msg, "usage_metadata", None)
    if isinstance(um, dict):
        meta["tokens_in"] = um.get("input_tokens")
        meta["tokens_out"] = um.get("output_tokens")
    return meta


def _as_messages(input) -> list:
    if isinstance(input, dict):
        return _as_messages(input.get("messages") or [])
    if isinstance(input, (list, tuple)):
        return list(input)
    return [input]


class LangChainPatcher:
    def __init__(self) -> None:
        self._restores: list[tuple[Any, str, Any]] = []
        self._installed = False

    def install(self, interceptor) -> list:
        if self._installed:
            return self._restores
        try:
            from langchain_core.language_models.chat_models import BaseChatModel
            from langchain_core.tools import BaseTool
        except ImportError:
            return self._restores

        # ---- LLM 决策点 ----
        orig_invoke = BaseChatModel.invoke
        orig_ainvoke = BaseChatModel.ainvoke

        def _llm_invoke(self, input, config=None, **kwargs):
            return self.__class__ and interceptor.sroute(
                kind="llm",
                agent_id=_model_id(self),
                input_context=Serializer.llm_input(_as_messages(input), _model_id(self), kwargs),
                call=lambda: orig_invoke(self, input, config, **kwargs),
                reconstruct=_reconstruct_llm,
                shape_output=_shape_llm,
                meta_fn=_llm_meta,
                make_modified_call=_mk_llm_call(orig_invoke, self, config, kwargs),
            )

        def _llm_ainvoke(self, input, config=None, **kwargs):
            return interceptor.aroute(
                kind="llm",
                agent_id=_model_id(self),
                input_context=Serializer.llm_input(_as_messages(input), _model_id(self), kwargs),
                call=lambda: orig_ainvoke(self, input, config, **kwargs),
                reconstruct=_reconstruct_llm,
                shape_output=_shape_llm,
                meta_fn=_llm_meta,
                make_modified_call=_mk_llm_call(orig_ainvoke, self, config, kwargs),
            )

        BaseChatModel.invoke = _llm_invoke
        BaseChatModel.ainvoke = _llm_ainvoke
        self._restores.append((BaseChatModel, "invoke", orig_invoke))
        self._restores.append((BaseChatModel, "ainvoke", orig_ainvoke))

        # ---- 工具决策点 ----
        orig_tool_invoke = BaseTool.invoke
        orig_tool_ainvoke = BaseTool.ainvoke

        def _tool_invoke(self, tool_input, config=None, **kwargs):
            return interceptor.sroute(
                kind="tool",
                agent_id=_tool_id(self),
                input_context=Serializer.tool_input(_tool_id(self), _jsonable(tool_input)),
                call=lambda: orig_tool_invoke(self, tool_input, config, **kwargs),
                reconstruct=_reconstruct_tool,
                shape_output=_shape_tool,
                meta_fn=lambda _r: {"tool": _tool_id(self)},
                make_modified_call=_mk_tool_call(orig_tool_invoke, self, config, kwargs),
            )

        def _tool_ainvoke(self, tool_input, config=None, **kwargs):
            return interceptor.aroute(
                kind="tool",
                agent_id=_tool_id(self),
                input_context=Serializer.tool_input(_tool_id(self), _jsonable(tool_input)),
                call=lambda: orig_tool_ainvoke(self, tool_input, config, **kwargs),
                reconstruct=_reconstruct_tool,
                shape_output=_shape_tool,
                meta_fn=lambda _r: {"tool": _tool_id(self)},
                make_modified_call=_mk_tool_call(orig_tool_ainvoke, self, config, kwargs),
            )

        BaseTool.invoke = _tool_invoke
        BaseTool.ainvoke = _tool_ainvoke
        self._restores.append((BaseTool, "invoke", orig_tool_invoke))
        self._restores.append((BaseTool, "ainvoke", orig_tool_ainvoke))

        self._installed = True
        return self._restores

    def uninstall(self) -> None:
        for obj, attr, orig in reversed(self._restores):
            setattr(obj, attr, orig)
        self._restores.clear()
        self._installed = False


def _mk_llm_call(orig, model, config, kwargs):
    def mk(inp: dict) -> Callable:
        msgs = _rebuild_messages(inp.get("messages") or [])
        merged = dict(kwargs)
        merged.update(inp.get("params") or {})
        return lambda: orig(model, msgs, config, **merged)

    return mk


def _mk_tool_call(orig, tool, config, kwargs):
    def mk(inp: dict) -> Callable:
        args = inp.get("args")
        return lambda: orig(tool, args, config, **kwargs)

    return mk


def _model_id(model) -> str:
    return getattr(model, "model_name", None) or getattr(model, "model", None) or type(model).__name__


def _tool_id(tool) -> str:
    return getattr(tool, "name", None) or type(tool).__name__


def _reconstruct_tool(out) -> Any:
    if out is None:
        return None
    if isinstance(out, dict):
        return out.get("result")
    return out


def _shape_tool(result) -> dict:
    return Serializer.tool_output(result)
