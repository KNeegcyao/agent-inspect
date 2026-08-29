# Agent-Inspect

> The DevTools for AI Agents. Pause. Step. Fork a branch and see *"what if I changed this one decision?"*

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#status)
[![Spec: 164 scenarios / 66 req](https://img.shields.io/badge/spec-158%20scenarios%20%2F%2063%20req-green.svg)](openspec/)

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

When you create a Fork you can also pick a **副作用策略** for the live suffix — independently for **LLM 决策点** and **工具调用**: `allow` (real calls, default), `dry-run` (the decision point records as *模拟执行(沙箱)* and never really runs), or `block` (records as *被沙箱阻止*). This isolates real side effects while you experiment — e.g. block the LLM to see how the agent behaves with no response, or block the tool so it never actually fires.

**Run it offline right now** (no API key needed — ships with a scripted chat model):

```bash
python examples/react_agent_demo.py
```

This records a real LangChain ReAct agent run, forks step 0 with a modified prompt, re-executes the fork, and leaves the two branches side-by-side in the panel for you to compare.

> The exact `pyproject.toml` packaging is being finalized (likely `pip install agent-inspect` once published; for now `pip install -e .` from the repo). See [Open Questions](docs/product.md#10-open-questions).

---

## Live debugging (Mode C): pause a running agent

Same one line, now with a **live debug toolbar** on the panel. No restart needed — while your agent is *running*, you can attach and intervene at decision-point boundaries:

1. **Attach** to the running trace (it keeps executing; attach is observation-only).
2. **Set a breakpoint** by decision kind (`llm` / `tool`) or by a text condition in the input.
3. When a decision point hits the breakpoint, execution **pauses** — the point's full input/output is inspectable.
4. **Step** executes exactly one more decision point, then pauses again.
5. At a paused point, **edit the input** and **Continue** — that decision point then really runs with your edited input.
6. **Continue** again to run to the next breakpoint or to completion.

```python
import agent_inspect

agent_inspect.start()          # panel opens; your agent runs & records as usual

# …run your LangChain/OpenAI agent (long-running). In the panel:
#   Attach → 断点(llm) → 命中暂停 → Step / 改输入 → Continue
```

**Try it live** (no API key needed):

```bash
python examples/react_agent_live_debug.py   # 运行中 attach → 断点暂停 → 步进 → 改输入 → 继续
```

Live debugging shares the same interceptor as Record/Replay/Fork — no second engine. Debug state (breakpoints) persists across sessions; pause/step are transient. Scope is per-trace, so concurrent agents are never disturbed.

---

## Branch diff: compare two branches, field by field

Once you have two branches (a recorded run + a fork, or two forks), select a **对比分支** in the panel and the two decision chains render side by side, aligned by step:

1. Pick a **主分支** and a **对比分支** in the toolbar. The compare picker groups every branch **by trace**, so you can compare branches from two separate runs (**cross-trace**) — each side is labeled with its owning trace's agent name.
2. Each aligned step gets a status: **same** (shared prefix or identical), **diff** (diverged), **only-left / only-right** (exists on one side only) — color-coded on the chain.
3. Click a divergent step: the inspector shows the **field-level diff** — every changed input/output field with its left-vs-right value; fields present on only one side are marked **增/删** rather than silently ignored.
4. A summary chip above the compare column totals the four statuses.
5. **采纳差异为 Fork**: with a divergent compare branch selected, hit the button above the comparison to preview every diff as a list of **Fork modifications** (input leaves are adopted as `input_context.<path>`, outputs as a whole-`output` override, taken from the right branch). Confirm to create a Fork of the left branch that carries those changes and re-executes from the earliest adopted step. The compare branch may live in a **different trace**: the preview labels both sides' owning trace, warns when they differ, and the new Fork is always created on the left (main) branch's trace.

```bash
python examples/react_agent_demo.py            # records a run + a fork → pick both branches → read the diff
python examples/react_agent_compare_traces.py  # records two runs (different prompts) → compare cross-trace
```

The diff is a **read-only** computation over the stored branches — no re-execution, no writes, no schema change. The **采纳** preview is likewise read-only (it only *maps* diffs to modifications); only the final **确认创建 Fork** writes a new branch.

---

## Cross-process tracing: tie a child run to its parent

A recorded trace is per-process today. When one Agent **spawns another process** (a worker, a sub-agent CLI, a cron), its decisions land in a separate trace with no link back to the one that started it. Cross-process tracing closes that gap with a single environment variable:

1. The parent process records its trace as usual (trace `P`).
2. When it spawns a child, it passes `AGENT_INSPECT_PARENT_TRACE=P` in the child's environment (same database file).
3. The child's `agent_inspect.start()` reads that variable, so its newly-created trace `C` is stored with `parent_trace_id=P`.
4. In the panel, `C` appears **indented** with a **「跨进程」** badge; opening `P` shows **子 trace × N**, and opening `C` shows a clickable **父 trace · P** chip.

```python
import agent_inspect

agent_inspect.start()   # parent: records trace P

# …when spawning a worker…
env = {**os.environ, "AGENT_INSPECT_PARENT_TRACE": P}
subprocess.run([python, "worker.py"], env=env)   # worker records trace C, parent=P
```

No env var set → behavior is identical to before (`parent_trace_id` is `None`). The core record path is untouched; only the new trace carries the parent link. Run it offline:

```bash
python examples/react_agent_cross_process.py   # 父进程记录 → 派生子进程(带 env)→ 子 trace 挂到父 trace 下
```

---

## Import, export & push external traces: eat *someone else's* trace and fork it

The debugger's raw material doesn't have to be a trace *you* recorded. Agent-Inspect imports span-export JSON following the OpenInference semantic conventions — the kind of file an observability platform or a colleague can hand you — and turns it into a first-class trace:

1. In the panel sidebar, hit **导入 trace** and pick a `.json` span export (OTLP JSON envelope or a flat span list; `openinference.span.kind` distinguishes LLM / tool spans).
2. The imported trace shows up with an **「导入」** badge — same decision-point model as self-recorded traces: full prompt in, output out, cause edges along the span tree.
3. Fork it, modify a step, and run **your** agent: the prefix replays deterministically from the imported outputs (zero real calls), the suffix really executes — you just ran a counterfactual on a production run you never recorded yourself.
4. And it goes both ways: the **导出** button on any trace header downloads the same format — hand your chain to a colleague, archive it outside the local DB, or re-import it later. Export → import roundtrips content-identically.
5. Prefer it pushed? The **推送** button delivers the same chain to any collector endpoint speaking the standard OTLP/HTTP JSON protocol (default `http://127.0.0.1:4318/v1/traces`) — zero new dependencies, delivery result and failures surfaced in the panel.

```bash
python examples/react_agent_import_trace.py   # 录一段 → 合成 span 导出 → 导入 → 在导入链路上 Fork → 导出再导入
```

---

## Core ideas

1. **A decision is a unit.** Every LLM call and every tool call is recorded as a *decision point* — full prompt in, full response out, with latency and tokens.
2. **Three modes, one engine.** *Replay* (read-only), *Fork* (the flagship), and *Live* (attach to a running agent with conditional breakpoints, pause, step, continue — and edit an input at a paused point). All three are one interceptor behaving three ways — not three features bolted together.
3. **Fork = recorded prefix + live suffix.** Free, deterministic replay up to your change; *real* execution after it. This is what unifies the old "time-travel (read-only) vs. modify-at-runtime (write)" contradiction.
4. **Built on OpenInference, not against it.** We extend the OpenInference semantic conventions with an Agent causal edge (`agent.step.cause`) rather than inventing our own — so your traces interop with the observability world you already have.

---

## What's in the MVP — and what deliberately isn't

**In the MVP:**
- Python-only SDK; auto-instruments **LangChain** and the **OpenAI** SDK.
- Replay (read-only) + **Counterfactual Fork** (the flagship).
- **Fork side-effect sandbox**: per-kind policies (`allow` / `dry-run` / `block`) for both **LLM decision points** and **tool calls** isolate real side effects on the live suffix.
- **Live (Mode C)**: attach to a running agent, conditional breakpoints, pause / step / continue, edit an input at a paused point.
- **Cross-process tracing**: a child process that declares `AGENT_INSPECT_PARENT_TRACE` links its trace to the parent's — indented + **「跨进程」** badge in the panel.
- **External trace import/export/push**: import a span-export JSON (OpenInference conventions) as a first-class trace — inspect it and fork it like any self-recorded run; export any trace back to the same format (roundtrip-equivalent); push a chain to any OTLP/HTTP collector endpoint (stdlib-only, zero new deps).
- One-line launch with a local panel; local file storage; zero external backend.
- Single-page React UI: decision tree, full-prompt inspection, fork interaction, branch diff (side-by-side, field-level), live debug toolbar.

**Deliberately out (follow-up changes):**
- TS / Go SDKs; framework auto-instrumentation beyond LangChain/OpenAI.
- VSCode / JetBrains plugins; built-in eval engine; ClickHouse; WASM large-graph rendering.

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
openspec validate --all                            # all specs pass
cd web && npm install && npm run build             # green (UI)
```

The MVP implementation change `add-agent-inspect-mvp`, the Live debugging (Mode C) change `add-live-debug-mode-c`, and the Branch diff change `add-branch-diff` are **applied and archived**; their proposals → specs → design → tasks live at [`openspec/changes/archive/2026-08-27-add-agent-inspect-mvp/`](openspec/changes/archive/2026-08-27-add-agent-inspect-mvp/), [`openspec/changes/archive/2026-08-27-add-live-debug-mode-c/`](openspec/changes/archive/2026-08-27-add-live-debug-mode-c/), and [`openspec/changes/archive/2026-08-27-add-branch-diff/`](openspec/changes/archive/2026-08-27-add-branch-diff/).

---

## Where the design rationale lives

- **[docs/product.md](docs/product.md)** — the product positioning doc (pain, positioning, the three-mode model, roadmap, competitor contrast).
- **[agent-inspect-proposal-v2.md](agent-inspect-proposal-v2.md)** — the full technical proposal (market framing, architecture, the critical decisions, risks).
- **[openspec/](openspec/)** — the spec-driven source of truth (`openspec/specs/README.md` is the capability baseline; the merged specs are the `fork/interception/recording/local-runtime/trace-ui/live-debug/branch-diff` capabilities; the archived changes `openspec/changes/archive/2026-08-27-add-agent-inspect-mvp/`, `openspec/changes/archive/2026-08-27-add-live-debug-mode-c/`, and `openspec/changes/archive/2026-08-27-add-branch-diff/` hold proposal → design → tasks).

Spec is source of truth; prose docs explain *why* the spec says what it says.

---

## Status

Pre-alpha / **MVP implemented, tested and archived**. The MVP (`add-agent-inspect-mvp`): one-line `agent_inspect.start()`, LangChain + OpenAI auto-instrumentation, Replay + Counterfactual Fork, local SQLite storage, single-page React panel. **Live debugging (Mode C)** (`add-live-debug-mode-c`): attach to a running agent, conditional breakpoints, pause / step / continue, edit input at a paused point. **Branch diff** (`add-branch-diff`): side-by-side compare of two branches with per-step status and field-level diff detail. **Fork side-effect sandbox** (`2026-08-28-fork-side-effect-sandbox`): per-kind policies isolate tool side effects on the live suffix. **Cross-process tracing** (`2026-08-28-cross-process-trace`): a child process declaring `AGENT_INSPECT_PARENT_TRACE` links its trace to the parent's. **LLM decision-point sandbox** (`2026-08-29-llm-decision-sandbox`): per-kind sandbox policies now cover LLM decision points too, independent of tool policy. **External trace import** (`import-openinference-traces`): import OpenInference span-export JSON as a first-class, forkable trace. **External trace export** (`export-openinference-traces`): export any trace to the same format; export → import roundtrips content-identically. **OTLP push** (`push-traces-otlp`): deliver a chain to any collector endpoint over OTLP/HTTP JSON, stdlib-only. **125 tests green** (unit + integration + e2e), `openspec validate --all` passes, specs merged into baseline. UI rendering is verified in-browser.

## License

Apache-2.0.
