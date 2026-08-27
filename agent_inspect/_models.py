"""决策点 / 分支 / trace 数据模型(内部实现,不进 spec)。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

LIFECYCLE_RUNNING = "running"
LIFECYCLE_DONE = "done"
LIFECYCLE_ABORTED = "aborted"

KIND_LLM = "llm"
KIND_TOOL = "tool"

ORIGIN_RECORD = "record"
ORIGIN_FORK = "fork"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class DecisionPoint:
    id: str
    trace_id: str
    branch_id: str
    step_index: int
    kind: str
    agent_id: str
    input_context: dict[str, Any] = field(default_factory=dict)
    output: Optional[dict[str, Any]] = None
    output_hash: Optional[str] = None
    cause_edge: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "branch_id": self.branch_id,
            "step_index": self.step_index,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "input_context": self.input_context,
            "output": self.output,
            "output_hash": self.output_hash,
            "cause_edge": self.cause_edge,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DecisionPoint":
        return cls(
            id=d["id"],
            trace_id=d["trace_id"],
            branch_id=d["branch_id"],
            step_index=d["step_index"],
            kind=d["kind"],
            agent_id=d["agent_id"],
            input_context=d.get("input_context", {}),
            output=d.get("output"),
            output_hash=d.get("output_hash"),
            cause_edge=d.get("cause_edge", []),
            meta=d.get("meta", {}),
        )


@dataclass
class Branch:
    id: str
    trace_id: str
    parent_branch_id: Optional[str]
    branch_from_step: int
    origin: str
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_branch_id": self.parent_branch_id,
            "branch_from_step": self.branch_from_step,
            "origin": self.origin,
            "note": self.note,
        }


@dataclass
class Trace:
    id: str
    started_at: float
    agent_name: str
    root_branch_id: Optional[str]
    lifecycle: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "agent_name": self.agent_name,
            "root_branch_id": self.root_branch_id,
            "lifecycle": self.lifecycle,
        }


@dataclass
class Breakpoint:
    """条件断点(kind / agent_id / 输入子串命中;不做任意代码)。"""

    id: str
    trace_id: str
    kind: Optional[str] = None
    agent_id: Optional[str] = None
    condition: Optional[str] = None
    enabled: bool = True
    created_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "condition": self.condition,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }


def now() -> float:
    return time.time()