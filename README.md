# Agent-Inspect

> The DevTools for AI Agents. Pause. Step. Fork a branch and see *"what if I changed this one decision?"*

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#status)
[![Spec: 69 scenarios / 30 req](https://img.shields.io/badge/spec-69%20scenarios%20%2F%2030%20req-green.svg)](openspec/)

**Agent-Inspect** is an interactive step-debugger for LLM Agents — not another tracing platform. It brings the Chrome DevTools / `pdb` experience to Agent development: drop in one line, and a local debug panel opens in your browser. You can inspect the full prompt at any decision point, change a prompt or a tool's return value, and fork a new branch to see what the Agent does *after the change* — without rerunning the whole thing.

---

## Why this exists

Most Agent tooling today is **observability**: LangFuse, Phoenix, OpenLLMetry record what *happened*, read-only, after the fact. That answers *"what did the Agent do?"*

It can't answer the question developers actually keep asking:

- *"The Agent got stuck in a loop — would a different prompt break it out?"*
- *"Why did it call that tool? If that tool had returned X, would the rest have gone differently?"*
- *"This run hallucinated at step 7 — if I lower the temperature there, is it fixed?"*

Those are **counterfactual** questions. Observation can't answer them. You have to *change* something and *re-execute*. That's a debugger's job, and there wasn't one for Agents.

Agent-Inspect is that debugger. Its flagship feature is **counterfactual fork**: take a recorded execution, replay its prefix deterministically, inject a change at one decision point, and **really re-run** everything after it — then compare the two branches side by side.

---

## What it is (and isn't)

| | LangFuse / Phoenix / OpenLLMetry | Agent-Inspect |
|---|---|---|
| Posture | Read-only viewer (after the fact) | Live debugger (pause, step, change) |
| Answers | "What happened?" | "What if I changed this?" |
| Setup | Self-hosted server + backend DB | **One line.** Local panel auto-opens |
| Cost to explore | Record a new run | Fork the existing one, re-run only the suffix |
| License | (varies, some MIT) | Apache-2.0 |

**It is not** a replacement for your observability stack. It pairs with it — you keep LangFuse for production, you reach for Agent-Inspect when you're *building and debugging* the Agent.

---

## Quickstart (the one line)

```python
import agent_inspect

agent_inspect.start()   # that's the whole setup — panel auto-opens in your browser

# ...your existing LangChain or OpenAI Agent, unchanged...
```

That's it. No server to deploy. No database to configure. Interception is **zero-cost-off by default** — if you remove the line, your Agent runs exactly as before.

**What you'll see:** a single-page panel rendering this run's decision chain — *think → tool → result* — as a tree. Click any decision point to read its full prompt. Hit **Fork**, change a prompt or a tool result, and the Agent re-executes the steps *after* your change while replaying the prefix for free (no real LLM calls on the prefix). Watch the two branches diverge, side by side.

> The exact `pyproject.toml` packaging is being finalized (likely `pip install agent-inspect` once published; for now `pip install -e .` from the repo). See [Open Questions](docs/product.md#10-open-questions).

---

## Core ideas

1. **A decision is a unit.** Every LLM call and every tool call is recorded as a *decision point* — full prompt in, full response out, with latency and tokens.
2. **Three modes, one engine.** *Replay* (read-only), *Fork* (the flagship), and (later) *Live* (attach to a running process with breakpoints). All three are one interceptor behaving three ways — not three features bolted together.
3. **Fork = recorded prefix + live suffix.** Free, deterministic replay up to your change; *real* execution after it. This is what unifies the old "time-travel (read-only) vs. modify-at-runtime (write)" contradiction.
4. **Built on OpenInference, not against it.** We extend the OpenInference semantic conventions with an Agent causal edge (`agent.step.cause`) rather than inventing our own — so your traces interop with the observability world you already have.

---

## What's in the MVP — and what deliberately isn't

**In the MVP:**
- Python-only SDK; auto-instruments **LangChain** and the **OpenAI** SDK.
- Replay (read-only) + **Counterfactual Fork** (the flagship).
- One-line launch with a local panel; local file storage; zero external backend.
- Single-page React UI: decision tree, full-prompt inspection, fork interaction, branch compare.

**Deliberately out (follow-up changes):**
- Live mode (Mode C: attach + conditional breakpoints + step). Phase 2.
- Fork side-effect sandbox. Phase 2 (for now: real execution is explicit, + a `dry_run` preview).
- TS / Go SDKs; framework auto-instrumentation beyond LangChain/OpenAI.
- VSCode / JetBrains plugins; built-in eval engine; ClickHouse; WASM large-graph rendering; multi-Agent cross-process tracing.

We'd rather ship a debugger that does *one thing* superbly than a platform that does *everything* adequately.

---

## Development (start here)

This repo is **spec-driven** — "align the spec, then write code" is mandatory, not optional. Read these before changing anything:

| For | Read |
|---|---|
| Protocol & hard rules (AI & human) | [**CLAUDE.md**](CLAUDE.md) |
| How to contribute (human-facing) | [**CONTRIBUTING.md**](CONTRIBUTING.md) |
| Where code goes (components, data model, dir tree) | [docs/architecture.md](docs/architecture.md) |
| What the interfaces look like (schema/HTTP/WS) | [docs/contracts.md](docs/contracts.md) |
| How to test (69 scenarios → tests) | [docs/testing.md](docs/testing.md) |
| What this is & positioning | [docs/product.md](docs/product.md) |

**Quickest sanity check** after cloning:
```bash
python -m pip install -e ".[dev]" && pytest -q   # green
openspec validate --all                            # 1 passed
cd ui && npm install && npm run build              # green (UI)
```

The current implementation change is `add-agent-inspect-mvp`; its tasks live at [`openspec/changes/add-agent-inspect-mvp/tasks.md`](openspec/changes/add-agent-inspect-mvp/tasks.md).

---

## Where the design rationale lives

- **[docs/product.md](docs/product.md)** — the product positioning doc (pain, positioning, the three-mode model, roadmap, competitor contrast).
- **[agent-inspect-proposal-v2.md](agent-inspect-proposal-v2.md)** — the full technical proposal (market framing, architecture, the critical decisions, risks).
- **[openspec/](openspec/)** — the spec-driven source of truth (`openspec/specs/README.md` is the capability baseline; `openspec/changes/add-agent-inspect-mvp/` is the current implementation change: proposal → specs → design → tasks).

Spec is source of truth; prose docs explain *why* the spec says what it says.

---

## Status

Pre-alpha / spec-complete. The specification (`openspec/`) is written, peer-reviewed, and validated (69 scenarios across 30 requirements). Code scaffolding is the current phase. See [tasks](openspec/changes/add-agent-inspect-mvp/tasks.md).

## License

Apache-2.0.
