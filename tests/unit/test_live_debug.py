"""Mode C live 调试单测(对应 spec `live-debug`)。

覆盖:断点命中(kind / 输入内容)、条件不命中、手动暂停/继续、单步、
暂停点修改输入后继续、作用域隔离、异步路径不阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from agent_inspect._context import MODE_RECORD, ExecutionCursor, reset_cursor, set_cursor
from agent_inspect.debug import DebugController
from agent_inspect.fork import ForkController
from agent_inspect.interceptor.base import Interceptor
from agent_inspect.recorder import Recorder

from tests.conftest import FakeLLM, run_agent


@pytest.fixture
def denv(store) -> SimpleNamespace:
    """带 DebugController 的最小运行环境(enable live 打标)。"""
    rec = Recorder(store, on_event=None)
    fork = ForkController(store)
    events: list[tuple[str, dict]] = []
    debug = DebugController(store, on_event=lambda name, payload: events.append((name, payload)))
    interceptor = Interceptor(rec, controller=fork, debug=debug)
    return SimpleNamespace(
        store=store, recorder=rec, fork=fork, debug=debug, interceptor=interceptor, events=events
    )


def _start_trace(denv, agent_name="agent"):
    return denv.store.create_trace_with_root(agent_name)


def _wait_paused(gate, step: int, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if gate.paused_at == step:
            return
        time.sleep(0.01)
    raise AssertionError(f"not paused at step {step}, state={gate.state()}")


def _shape(x):
    return {"content": x}


def _recon(d):
    return d["content"] if d else None


def _resolved_input(denv, trace_id, branch_id, step: int):
    """读取某步落盘决策点的完整输入(经 context diff / blob 解析)。"""
    pts = denv.store.get_decision_points(trace_id, branch_id)
    return denv.recorder.serializer.resolve_dp(
        denv.store, pts[step], denv.recorder.context_snap
    )["input_context"]


class _AgentThread:
    """在后台线程跑 Agent(consult 阻塞时不卡主线程,主线程发调试指令)。"""

    def __init__(self, denv, trace_id, branch_id, *, inputs=None, n=None, scripted=None,
                 make_modified_call=None, kind="llm"):
        self.denv = denv
        self.trace_id = trace_id
        self.branch_id = branch_id
        self.inputs = inputs or [{"messages": [{"role": "user", "content": "hi"}], "model": "fake"}] * (n or 1)
        self.llm = FakeLLM(scripted or ["s%d" % i for i in range(len(self.inputs))])
        self.make_modified_call = make_modified_call
        self.kind = kind
        self.outs = []
        self.err = None
        self.done = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        cursor = ExecutionCursor(
            trace_id=self.trace_id, branch_id=self.branch_id, mode=MODE_RECORD, live_debug=True
        )
        token = set_cursor(cursor)
        try:
            for inp in self.inputs:
                self.outs.append(
                    self.denv.interceptor.sroute(
                        kind=self.kind,
                        agent_id="fake-llm",
                        input_context=inp,
                        call=lambda: self.llm.call(),
                        reconstruct=_recon,
                        shape_output=_shape,
                        make_modified_call=self.make_modified_call,
                    )
                )
        except BaseException as e:  # noqa: BLE001
            self.err = e
        finally:
            reset_cursor(token)
            self.done.set()

    def start(self):
        self._t.start()
        return self

    def join(self, timeout: float = 3.0):
        return self.done.wait(timeout)


# ---------------------------------------------------------------------------
# 断点命中与条件
# ---------------------------------------------------------------------------
def test_breakpoint_kind_hit_and_continue(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.add_breakpoint(kind="llm")

    th = _AgentThread(denv, trace.id, root.id, n=3).start()
    _wait_paused(gate, 0)
    assert gate.state()["paused_at"] == 0
    gate.resume()
    _wait_paused(gate, 1)  # 断点仍命中 → 再次暂停
    gate.resume()
    _wait_paused(gate, 2)
    gate.resume()
    assert th.join()
    assert th.outs == ["s0", "s1", "s2"]
    assert th.llm.calls == 3


def test_breakpoint_by_input_condition(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.add_breakpoint(condition="secret")

    inputs = [
        {"messages": [{"role": "user", "content": "hello"}], "model": "fake"},
        {"messages": [{"role": "user", "content": "the secret word"}], "model": "fake"},
        {"messages": [{"role": "user", "content": "bye"}], "model": "fake"},
    ]
    th = _AgentThread(denv, trace.id, root.id, inputs=inputs).start()
    # step1 含 secret → 暂停;step0/2 不含 → 放行
    _wait_paused(gate, 1)
    gate.resume()
    assert th.join()
    assert th.outs == ["s0", "s1", "s2"]


def test_breakpoint_tool_kind_ignores_llm(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.add_breakpoint(kind="tool")

    inputs = [{"messages": [], "model": "fake"}] * 2
    th = _AgentThread(denv, trace.id, root.id, inputs=inputs, kind="llm").start()
    # 断点为 tool,llm 决策点全部放行
    assert th.join()
    assert th.outs == ["s0", "s1"]


def test_breakpoint_no_match_completes_without_block(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.add_breakpoint(condition="never-present")
    th = _AgentThread(denv, trace.id, root.id, n=3).start()
    assert th.join()
    assert gate.state()["paused_at"] is None
    assert "trace.paused" not in [n for n, _ in denv.events]


def test_not_attached_zero_semantics(denv):
    trace, root = _start_trace(denv)
    # 不 attach:即便有断点也放行(附加不改变执行)
    denv.debug.ensure_gate(trace.id).add_breakpoint(kind="llm")
    th = _AgentThread(denv, trace.id, root.id, n=3).start()
    assert th.join()
    assert th.outs == ["s0", "s1", "s2"]


# ---------------------------------------------------------------------------
# 暂停 / 继续 / 单步
# ---------------------------------------------------------------------------
def test_manual_pause_then_continue(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=3).start()
    _wait_paused(gate, 0)  # 手动暂停在下一个决策点边界生效
    gate.resume()
    assert th.join()  # 继续后放行至完成
    assert th.outs == ["s0", "s1", "s2"]


def test_step_executes_one_point_then_pauses(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=3).start()
    _wait_paused(gate, 0)
    gate.step()
    _wait_paused(gate, 1)  # 恰执行一个决策点后在新暂停点停下
    gate.step()
    _wait_paused(gate, 2)
    gate.step()
    assert th.join()  # 最后一个决策点执行后无后续 → 完成
    assert th.outs == ["s0", "s1", "s2"]
    assert th.llm.calls == 3


def test_stale_step_command_ignored(denv):
    """释放指令绑定暂停点:重复/过期 step(at_step) 不误放已前进到的暂停点。

    网络重试会把同一条 step 指令投递两次;若无绑定,第二次会在下一个暂停点
    立即放行,表现为"单步跳了两步"(回归:live-debug e2e 偶发 paused_at=2)。
    """
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=3).start()
    _wait_paused(gate, 0)
    gate.step(at_step=0)
    _wait_paused(gate, 1)
    gate.step(at_step=0)  # 过期指令(at_step 仍是旧暂停点)→ 忽略
    time.sleep(0.05)
    assert gate.state()["paused_at"] == 1
    gate.step(at_step=1)  # 匹配当前暂停点 → 放行
    _wait_paused(gate, 2)
    gate.step(at_step=1)  # 又一条过期指令 → 忽略
    time.sleep(0.05)
    assert gate.state()["paused_at"] == 2
    gate.resume(at_step=2)
    assert th.join()
    assert th.outs == ["s0", "s1", "s2"]
    assert th.llm.calls == 3


def test_step_mismatched_at_step_does_not_release(denv):
    """at_step 与当前暂停点不匹配 → 指令忽略,agent 原地保持暂停。"""
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=1).start()
    _wait_paused(gate, 0)
    assert gate.step(at_step=99) is False
    time.sleep(0.05)
    assert gate.state()["paused_at"] == 0  # 仍暂停在原点
    gate.resume()
    assert th.join()
    assert th.outs == ["s0"]


def test_duplicate_modify_does_not_release_next_pause(denv):
    """modify 放行绑定其目标 step:重复投递的 modify 不误放后续暂停点。"""
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.add_breakpoint(kind="llm")  # 每个决策点都命中 → modify 放行后停到 step1
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=2).start()
    _wait_paused(gate, 0)
    gate.modify(step=0, field="messages[0].content", value="EDITED", action="continue")
    _wait_paused(gate, 1)  # 放行后断点再次命中
    gate.modify(step=0, field="messages[0].content", value="EDITED", action="continue")  # 重复投递
    time.sleep(0.05)
    assert gate.state()["paused_at"] == 1  # 未被过期 modify 误放
    gate.resume()
    assert th.join()
    assert th.outs == ["s0", "s1"]


def test_pause_after_continue_takes_effect_next_point(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=4).start()
    _wait_paused(gate, 0)
    gate.resume()
    gate.pause()  # 继续运行途中再次请求暂停
    _wait_paused(gate, 1)  # 下一决策点边界生效
    gate.resume()
    assert th.join()


# ---------------------------------------------------------------------------
# 暂停点修改输入后继续
# ---------------------------------------------------------------------------
def test_modify_input_then_continue_uses_modified(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()

    seen_inputs = []

    def mkc(inp):
        seen_inputs.append(inp)
        return lambda: "echo:" + inp["messages"][0]["content"]

    th = _AgentThread(
        denv, trace.id, root.id, n=1,
        scripted=["ignored"],
        make_modified_call=mkc,
    ).start()
    _wait_paused(gate, 0)
    gate.modify(step=0, field="messages[0].content", value="EDITED", action="continue")
    assert th.join()
    assert th.outs == ["echo:EDITED"]  # 以替换后的输入真实执行
    assert seen_inputs and seen_inputs[0]["messages"][0]["content"] == "EDITED"
    # 落盘的也是实际执行的输入
    assert _resolved_input(denv, trace.id, root.id, 0)["messages"][0]["content"] == "EDITED"


def test_continue_without_modify_uses_original(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=1).start()
    _wait_paused(gate, 0)
    gate.resume()  # 不做修改直接继续 → 原输入执行
    assert th.join()
    assert th.outs == ["s0"]
    assert _resolved_input(denv, trace.id, root.id, 0)["messages"][0]["content"] == "hi"


# ---------------------------------------------------------------------------
# 作用域隔离
# ---------------------------------------------------------------------------
def test_breakpoint_isolated_per_trace(denv):
    trace_a, root_a = _start_trace(denv, "a")
    trace_b, root_b = _start_trace(denv, "b")

    gate_a = denv.debug.ensure_gate(trace_a.id)
    gate_a.attach()
    gate_a.add_breakpoint(kind="llm")

    # trace B 无断点 → 自由执行(即使 A 已附加断点)
    th_b = _AgentThread(denv, trace_b.id, root_b.id, n=2).start()
    assert th_b.join()
    assert th_b.outs == ["s0", "s1"]

    # trace A 命中断点 → 暂停
    th_a = _AgentThread(denv, trace_a.id, root_a.id, n=1).start()
    _wait_paused(gate_a, 0)
    gate_a.resume()
    assert th_a.join()


def test_modify_affects_only_own_branch(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()
    th = _AgentThread(denv, trace.id, root.id, n=1).start()
    _wait_paused(gate, 0)
    gate.modify(step=0, field="messages[0].content", value="X", action="continue")
    assert th.join()
    # 落盘为实际执行的输入 → 仅当前分支受影响
    assert _resolved_input(denv, trace.id, root.id, 0)["messages"][0]["content"] == "X"


# ---------------------------------------------------------------------------
# 异步路径:暂停不阻塞事件循环
# ---------------------------------------------------------------------------
def test_async_aroute_pause_does_not_block_loop(denv):
    trace, root = _start_trace(denv)
    gate = denv.debug.ensure_gate(trace.id)
    gate.attach()
    gate.pause()

    async def _async_val(v):
        await asyncio.sleep(0)
        return v

    async def main():
        cursor = ExecutionCursor(
            trace_id=trace.id, branch_id=root.id, mode=MODE_RECORD, live_debug=True
        )
        token = set_cursor(cursor)
        try:
            async def one(val):
                return await denv.interceptor.aroute(
                    kind="llm",
                    agent_id="fake-llm",
                    input_context={"messages": [], "model": "fake"},
                    call=lambda: _async_val(val),
                    reconstruct=_recon,
                    shape_output=_shape,
                )

            task = asyncio.create_task(one("x"))
            deadline = time.time() + 3
            while gate.paused_at != 0 and time.time() < deadline:
                await asyncio.sleep(0.01)
            assert gate.paused_at == 0
            # 暂停期间事件循环仍空闲:短 sleep 立即返回(而非被阻塞拖住)
            t0 = time.perf_counter()
            await asyncio.sleep(0.05)
            assert time.perf_counter() - t0 < 0.5
            gate.resume()
            out = await task
            return out
        finally:
            reset_cursor(token)

    assert asyncio.run(main()) == "x"
