"""SQLite 读写与查询(串行落盘,单写者)。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from . import schema
from ... import _models as m


class Store:
    """本地单文件 SQLite store。线程安全:写操作串行化。"""

    def __init__(self, path: str) -> None:
        self._conn = schema.connect(path)
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- traces ----
    def create_trace_with_root(self, agent_name: str) -> tuple[m.Trace, m.Branch]:
        """创建一条新 trace 及其根分支(record 基线)。先落分支再落 trace,避免外键悬空。"""
        trace = m.Trace(
            id=m.new_id("tr"),
            started_at=m.now(),
            agent_name=agent_name,
            root_branch_id=None,
            lifecycle=m.LIFECYCLE_RUNNING,
        )
        branch = m.Branch(
            id=m.new_id("br"),
            trace_id=trace.id,
            parent_branch_id=None,
            branch_from_step=0,
            origin=m.ORIGIN_RECORD,
            note=None,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO branches(id, trace_id, parent_branch_id, branch_from_step, origin, note) "
                "VALUES(?,?,?,?,?,?)",
                (branch.id, branch.trace_id, branch.parent_branch_id, branch.branch_from_step, branch.origin, branch.note),
            )
            self._conn.execute(
                "INSERT INTO traces(id, started_at, agent_name, root_branch_id, lifecycle) "
                "VALUES(?,?,?,?,?)",
                (trace.id, trace.started_at, trace.agent_name, branch.id, trace.lifecycle),
            )
            self._conn.commit()
        trace.root_branch_id = branch.id
        return trace, branch

    def create_trace(self, agent_name: str, root_branch_id: str) -> m.Trace:
        t = m.Trace(
            id=m.new_id("tr"),
            started_at=m.now(),
            agent_name=agent_name,
            root_branch_id=root_branch_id,
            lifecycle=m.LIFECYCLE_RUNNING,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO traces(id, started_at, agent_name, root_branch_id, lifecycle) "
                "VALUES(?,?,?,?,?)",
                (t.id, t.started_at, t.agent_name, t.root_branch_id, t.lifecycle),
            )
            self._conn.commit()
        return t

    def set_trace_lifecycle(self, trace_id: str, lifecycle: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE traces SET lifecycle=? WHERE id=?", (lifecycle, trace_id)
            )
            self._conn.commit()

    def get_trace(self, trace_id: str) -> Optional[m.Trace]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, started_at, agent_name, root_branch_id, lifecycle FROM traces WHERE id=?",
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        return m.Trace(
            id=row[0],
            started_at=row[1],
            agent_name=row[2],
            root_branch_id=row[3],
            lifecycle=row[4],
        )

    def list_traces(self, lifecycle: Optional[str] = None) -> list[m.Trace]:
        q = "SELECT id, started_at, agent_name, root_branch_id, lifecycle FROM traces"
        args: tuple = ()
        if lifecycle is not None:
            q += " WHERE lifecycle=?"
            args = (lifecycle,)
        q += " ORDER BY started_at DESC"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [
            m.Trace(id=r[0], started_at=r[1], agent_name=r[2], root_branch_id=r[3], lifecycle=r[4])
            for r in rows
        ]

    # ---- branches ----
    def create_branch(
        self,
        trace_id: str,
        parent_branch_id: Optional[str],
        branch_from_step: int,
        origin: str,
        note: Optional[str] = None,
    ) -> m.Branch:
        b = m.Branch(
            id=m.new_id("br"),
            trace_id=trace_id,
            parent_branch_id=parent_branch_id,
            branch_from_step=branch_from_step,
            origin=origin,
            note=note,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO branches(id, trace_id, parent_branch_id, branch_from_step, origin, note) "
                "VALUES(?,?,?,?,?,?)",
                (b.id, b.trace_id, b.parent_branch_id, b.branch_from_step, b.origin, b.note),
            )
            self._conn.commit()
        return b

    def get_branch(self, branch_id: str) -> Optional[m.Branch]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, trace_id, parent_branch_id, branch_from_step, origin, note "
                "FROM branches WHERE id=?",
                (branch_id,),
            ).fetchone()
        if row is None:
            return None
        return m.Branch(
            id=row[0],
            trace_id=row[1],
            parent_branch_id=row[2],
            branch_from_step=row[3],
            origin=row[4],
            note=row[5],
        )

    def list_branches(self, trace_id: str) -> list[m.Branch]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, trace_id, parent_branch_id, branch_from_step, origin, note "
                "FROM branches WHERE trace_id=? ORDER BY rowid",
                (trace_id,),
            ).fetchall()
        return [
            m.Branch(
                id=r[0],
                trace_id=r[1],
                parent_branch_id=r[2],
                branch_from_step=r[3],
                origin=r[4],
                note=r[5],
            )
            for r in rows
        ]

    # ---- decision points ----
    def write_decision_point(self, dp: m.DecisionPoint) -> None:
        input_ref = _json_dumps(dp.input_context)
        output_ref = _json_dumps(dp.output) if dp.output is not None else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO decision_points(id, trace_id, branch_id, step_index, kind, agent_id, "
                "input_context_ref, output_ref, output_hash, meta_json, cause_edge_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    dp.id,
                    dp.trace_id,
                    dp.branch_id,
                    dp.step_index,
                    dp.kind,
                    dp.agent_id,
                    input_ref,
                    output_ref,
                    dp.output_hash,
                    _json_dumps(dp.meta),
                    _json_dumps(dp.cause_edge),
                ),
            )
            self._conn.commit()

    def get_decision_points(
        self, trace_id: str, branch_id: str, from_step: int = 0, to_step: Optional[int] = None
    ) -> list[m.DecisionPoint]:
        q = (
            "SELECT id, trace_id, branch_id, step_index, kind, agent_id, input_context_ref, "
            "output_ref, output_hash, meta_json, cause_edge_json "
            "FROM decision_points WHERE trace_id=? AND branch_id=? AND step_index>=?"
        )
        args: list[Any] = [trace_id, branch_id, from_step]
        if to_step is not None:
            q += " AND step_index<=?"
            args.append(to_step)
        q += " ORDER BY step_index"
        with self._lock:
            rows = self._conn.execute(q, tuple(args)).fetchall()
        return [self._row_to_dp(r) for r in rows]

    def get_decision_point(self, trace_id: str, branch_id: str, step_index: int) -> Optional[m.DecisionPoint]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, trace_id, branch_id, step_index, kind, agent_id, input_context_ref, "
                "output_ref, output_hash, meta_json, cause_edge_json "
                "FROM decision_points WHERE trace_id=? AND branch_id=? AND step_index=?",
                (trace_id, branch_id, step_index),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dp(row)

    @staticmethod
    def _row_to_dp(row: tuple) -> m.DecisionPoint:
        return m.DecisionPoint(
            id=row[0],
            trace_id=row[1],
            branch_id=row[2],
            step_index=row[3],
            kind=row[4],
            agent_id=row[5],
            input_context=_json_loads(row[6]),
            output=_json_loads(row[7]) if row[7] is not None else None,
            output_hash=row[8],
            meta=_json_loads(row[9]),
            cause_edge=_json_loads(row[10]),
        )

    def count_decision_points(self, trace_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decision_points WHERE trace_id=?", (trace_id,)
            ).fetchone()
        return int(row[0])

    def last_step_before(self, branch_id: str, step_index: int) -> Optional[int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT step_index FROM decision_points WHERE branch_id=? AND step_index<? "
                "ORDER BY step_index DESC LIMIT 1",
                (branch_id, step_index),
            ).fetchone()
        return row[0] if row else None

    # ---- blobs ----
    def put_blob(self, hash_: str, kind: str, size: int, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, kind, size, content) VALUES(?,?,?,?)",
                (hash_, kind, size, content),
            )
            self._conn.commit()

    def get_blob(self, hash_: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT content FROM blobs WHERE hash=?", (hash_,)
            ).fetchone()
        return row[0] if row else None

    # ---- context diffs ----
    def write_context_diff(
        self, diff_id: str, branch_id: str, step_index: int, diff_against_step: Optional[int], payload: Any
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO context_diffs(id, branch_id, step_index, diff_against_step, payload_json) "
                "VALUES(?,?,?,?,?)",
                (diff_id, branch_id, step_index, diff_against_step, _json_dumps(payload)),
            )
            self._conn.commit()

    def get_context_diff(self, branch_id: str, step_index: int) -> Optional[tuple[Optional[int], Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT diff_against_step, payload_json FROM context_diffs "
                "WHERE branch_id=? AND step_index=?",
                (branch_id, step_index),
            ).fetchone()
        if row is None:
            return None
        return row[0], _json_loads(row[1])

    def get_context_diffs(
        self, branch_id: str, to_step: int
    ) -> list[tuple[int, Optional[int], Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT step_index, diff_against_step, payload_json FROM context_diffs "
                "WHERE branch_id=? AND step_index<=? ORDER BY step_index",
                (branch_id, to_step),
            ).fetchall()
        return [(r[0], r[1], _json_loads(r[2])) for r in rows]

    # ---- breakpoints (Mode C live debug,跨会话保留)----
    def add_breakpoint(
        self,
        trace_id: str,
        *,
        kind: Optional[str] = None,
        agent_id: Optional[str] = None,
        condition: Optional[str] = None,
    ) -> m.Breakpoint:
        bp = m.Breakpoint(
            id=m.new_id("bp"),
            trace_id=trace_id,
            kind=kind,
            agent_id=agent_id,
            condition=condition,
            enabled=True,
            created_at=m.now(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO breakpoints(id, trace_id, kind, agent_id, condition, enabled, created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (bp.id, bp.trace_id, bp.kind, bp.agent_id, bp.condition, 1, bp.created_at),
            )
            self._conn.commit()
        return bp

    def list_breakpoints(self, trace_id: str) -> list[m.Breakpoint]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, trace_id, kind, agent_id, condition, enabled, created_at "
                "FROM breakpoints WHERE trace_id=? ORDER BY created_at",
                (trace_id,),
            ).fetchall()
        return [m.Breakpoint(*r) for r in rows]

    def remove_breakpoint(self, trace_id: str, bp_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM breakpoints WHERE trace_id=? AND id=?", (trace_id, bp_id)
            )
            self._conn.commit()
        return cur.rowcount > 0


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(s: str) -> Any:
    return json.loads(s)