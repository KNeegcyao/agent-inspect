// OpenAI Node SDK 自动插桩:包装 Chat.Completions.prototype.create。
// 缺包静默跳过;stream:true 原样放行;输入/输出契约形态与 Python 侧一致。
import type { Interceptor } from "../interceptor.js";

export interface Patcher {
  restore(): void;
}

// 最小响应形对象:常见 Agent 循环(content/tool_calls/usage)零改动回放
interface ReplayResponse {
  id: string | null;
  model: string | null;
  choices: {
    message: {
      role: "assistant";
      content: string | null;
      tool_calls: unknown[] | null;
    };
    index: number;
    finish_reason: string;
  }[];
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
}

function reconstruct(out: Record<string, unknown> | null): ReplayResponse | null {
  if (!out) return null;
  const message = {
    role: "assistant" as const,
    content: (out["content"] as string | null) ?? null,
    tool_calls: (out["tool_calls"] as unknown[] | null) ?? null,
  };
  return {
    id: (out["id"] as string | null) ?? null,
    model: (out["model"] as string | null) ?? null,
    choices: [{ message, index: 0, finish_reason: "stop" }],
    usage: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    },
  };
}

function shapeResponse(resp: unknown): Record<string, unknown> {
  const r = resp as {
    id?: string;
    model?: string;
    choices?: { message?: { content?: string | null; tool_calls?: unknown[] } }[];
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };
  const msg = r.choices?.[0]?.message;
  const toolCalls = (msg?.tool_calls ?? []).map((tc) => {
    const t = tc as { function?: { name?: string; arguments?: string }; id?: string };
    let args: unknown = t.function?.arguments;
    if (typeof args === "string") {
      try {
        args = JSON.parse(args);
      } catch {
        /* 保留原文本 */
      }
    }
    return { name: t.function?.name, args, id: t.id };
  });
  const out: Record<string, unknown> = {
    content: msg?.content ?? null,
    tool_calls: toolCalls,
    id: r.id ?? null,
    model: r.model ?? null,
  };
  if (r.usage) out["usage"] = r.usage;
  return out;
}

export async function installOpenAIInterceptor(interceptor: Interceptor): Promise<Patcher | null> {
  // 运行时零依赖:openai 是宿主可选依赖,缺失则静默跳过(零行为变化)
  let mod: any;
  try {
    mod = await import("openai");
  } catch {
    return null;
  }
  const OpenAI = mod.default ?? mod;
  const Completions = OpenAI?.Chat?.Completions;
  if (!Completions?.prototype || typeof Completions.prototype.create !== "function") {
    return null;
  }
  const proto = Completions.prototype as any;
  const origCreate = proto.create;

  proto.create = function patchedCreate(this: any, body: any, options?: any) {
    if (body && body.stream) {
      return origCreate.call(this, body, options); // 流式原样放行(MVP 不插桩)
    }
    const { messages, model, ...rest } = body ?? {};
    const params = Object.keys(rest).length ? rest : {};
    return interceptor.route({
      kind: "llm",
      agentId: model ?? "openai",
      inputContext: { messages, model, params },
      call: () => origCreate.call(this, body, options),
      reconstruct: (out) => reconstruct(out),
      shapeOutput: shapeResponse,
      makeModifiedCall: (patched) => {
        const patchedBody = {
          ...body,
          messages: patched["messages"],
          model: patched["model"],
          ...(patched["params"] as Record<string, unknown>),
        };
        return () => origCreate.call(this, patchedBody, options);
      },
    });
  };

  return {
    restore() {
      proto.create = origCreate;
    },
  };
}
