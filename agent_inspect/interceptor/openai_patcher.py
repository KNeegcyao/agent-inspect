"""OpenAI 兼容 SDK 自动插桩。

包装「高语义稳定入口」`chat.completions.create`(同步 + 异步),把每次补全请求
登记为 LLM 决策点(design.md 决策,拒绝全进程 monkeypatch socket)。
兼容 openai 官方 SDK 与任何按其约定实现的兼容库(litellm/本地网关等)。

openai 由用户项目自带,不硬绑 runtime deps;未安装时插桩静默跳过。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Optional

from ..recorder.serializer import Serializer, _jsonable

try:  # 允许在未装 openai 的环境导入本模块而不报错
    import openai as _openai
except Exception:  # noqa: BLE001
    _openai = None


def _reconstruct_response(out: Optional[dict]):
    """把契约 output dict 重建为最小可用的 ChatCompletion 形状对象。

    只提供用户代码常用的属性路径(choices[0].message.content / tool_calls、
    usage、model、id),保证回放代码零改动。
    """
    if out is None:
        return None
    message = SimpleNamespace(
        content=out.get("content"),
        tool_calls=out.get("tool_calls") or None,
        role="assistant",
    )
    choice = SimpleNamespace(message=message, index=0, finish_reason="stop")
    usage = out.get("usage")
    return SimpleNamespace(
        id=out.get("id"),
        model=out.get("model"),
        choices=[choice],
        usage=SimpleNamespace(
            prompt_tokens=usage.get("prompt_tokens", 0) if usage else 0,
            completion_tokens=usage.get("completion_tokens", 0) if usage else 0,
            total_tokens=usage.get("total_tokens", 0) if usage else 0,
        ),
    )


def _shape_response(resp) -> dict:
    choice = resp.choices[0] if getattr(resp, "choices", None) else None
    msg = choice.message if choice is not None else None
    content = getattr(msg, "content", None)
    tool_calls = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        tool_calls.append(
            {
                "id": getattr(tc, "id", None),
                "type": getattr(tc, "type", "function"),
                "function": {
                    "name": getattr(fn, "name", None) if fn else None,
                    "arguments": getattr(fn, "arguments", None) if fn else None,
                },
            }
        )
    usage = getattr(resp, "usage", None)
    return {
        "content": content,
        "tool_calls": tool_calls,
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
        "model": getattr(resp, "model", None),
        "id": getattr(resp, "id", None),
    }


def _response_meta(resp) -> dict:
    usage = getattr(resp, "usage", None)
    meta: dict = {}
    if usage is not None:
        meta["tokens_in"] = getattr(usage, "prompt_tokens", None)
        meta["tokens_out"] = getattr(usage, "completion_tokens", None)
    return meta


class OpenAIPatcher:
    """包装 `chat.completions.create`(sync + async)为 LLM 决策点。"""

    def __init__(self) -> None:
        self._restores: list[tuple[Any, str, Any]] = []
        self._installed = False

    def install(self, interceptor) -> list:
        if self._installed:
            return self._restores
        if _openai is None:
            return self._restores
        try:
            from openai.resources.chat.completions import (
                AsyncCompletions,
                Completions,
            )
        except Exception:  # noqa: BLE001 - 兼容库路径差异,静默跳过
            return self._restores

        # ---- 同步 ----
        orig_create = Completions.create

        def _create(self, **kwargs):
            return interceptor.sroute(
                kind="llm",
                agent_id=_model_from(kwargs),
                input_context=_input_context(kwargs),
                call=lambda: orig_create(self, **kwargs),
                reconstruct=_reconstruct_response,
                shape_output=_shape_response,
                meta_fn=_response_meta,
                make_modified_call=_mk_create_call(orig_create, self),
            )

        Completions.create = _create
        self._restores.append((Completions, "create", orig_create))

        # ---- 异步 ----
        orig_acreate = AsyncCompletions.create

        async def _acreate(self, **kwargs):
            return await interceptor.aroute(
                kind="llm",
                agent_id=_model_from(kwargs),
                input_context=_input_context(kwargs),
                call=lambda: orig_acreate(self, **kwargs),
                reconstruct=_reconstruct_response,
                shape_output=_shape_response,
                meta_fn=_response_meta,
                make_modified_call=_mk_create_call(orig_acreate, self),
            )

        AsyncCompletions.create = _acreate
        self._restores.append((AsyncCompletions, "create", orig_acreate))

        self._installed = True
        return self._restores

    def uninstall(self) -> None:
        for obj, attr, orig in reversed(self._restores):
            setattr(obj, attr, orig)
        self._restores.clear()
        self._installed = False


def _input_context(kwargs: dict) -> dict:
    return {
        "messages": _jsonable(kwargs.get("messages") or []),
        "model": kwargs.get("model"),
        "params": {
            k: _jsonable(v)
            for k, v in kwargs.items()
            if k not in ("messages", "model")
        },
    }


def _model_from(kwargs: dict) -> str:
    return kwargs.get("model") or "openai"


def _mk_create_call(orig, client):
    def mk(inp: dict) -> Callable:
        merged = dict(inp.get("params") or {})
        merged["messages"] = inp.get("messages") or []
        merged["model"] = inp.get("model") or "gpt-4o-mini"
        return lambda: orig(client, **merged)

    return mk
