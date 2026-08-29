"""跨进程追踪单元测试(spec `cross-process-trace`)。"""
from __future__ import annotations

import sqlite3

from agent_inspect._server.store.schema import connect
from agent_inspect._models import new_id


def test_create_with_parent_id_persists_and_to_dict(store):
    """带父 id 创建 → parent_trace_id 落库正确;to_dict 携带该字段。"""
    parent, _ = store.create_trace_with_root("parent-agent")
    child, _ = store.create_trace_with_root("child-agent", parent_trace_id=parent.id)

    got = store.get_trace(child.id)
    assert got is not None
    assert got.parent_trace_id == parent.id
    assert got.to_dict()["parent_trace_id"] == parent.id
    # 不带父 id 时默认 None 且 to_dict 携带
    assert parent.parent_trace_id is None
    assert parent.to_dict()["parent_trace_id"] is None


def test_list_child_traces_returns_direct_children(store):
    """list_child_traces(parent) 返回直接子 trace。"""
    parent, _ = store.create_trace_with_root("p")
    c1, _ = store.create_trace_with_root("c1", parent_trace_id=parent.id)
    c2, _ = store.create_trace_with_root("c2", parent_trace_id=parent.id)
    other, _ = store.create_trace_with_root("other")

    children = store.list_child_traces(parent.id)
    ids = {c.id for c in children}
    assert ids == {c1.id, c2.id}
    assert other.id not in ids
    # 直接子(不含孙)
    grand, _ = store.create_trace_with_root("grand", parent_trace_id=c1.id)
    assert store.list_child_traces(c1.id)[0].id == grand.id
    assert grand.id not in store.list_child_traces(parent.id)


def test_old_db_migration_sets_parent_null(tmp_path):
    """旧库(无列)打开迁移后:老行父 id 为 None,新列可正常写入。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE traces (
            id TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            agent_name TEXT NOT NULL,
            root_branch_id TEXT,
            lifecycle TEXT NOT NULL
        );
        INSERT INTO traces(id, started_at, agent_name, root_branch_id, lifecycle)
        VALUES('tr_legacy', 1.0, 'old', NULL, 'done');
        """
    )
    conn.commit()
    conn.close()

    from agent_inspect._server.store.queries import Store

    s = Store(str(path))
    try:
        legacy = s.get_trace("tr_legacy")
        assert legacy is not None
        assert legacy.parent_trace_id is None
        assert legacy.to_dict()["parent_trace_id"] is None
        # 迁移后新列可正常写入
        t, _ = s.create_trace_with_root("new", parent_trace_id="tr_legacy")
        assert s.get_trace(t.id).parent_trace_id == "tr_legacy"
    finally:
        s.close()


def test_create_trace_explicit_parent(store):
    """create_trace(显式 root_branch_id)同样携带 parent_trace_id。"""
    parent, root = store.create_trace_with_root("p")
    child = store.create_trace("c", root.id, parent_trace_id=parent.id)
    assert store.get_trace(child.id).parent_trace_id == parent.id
