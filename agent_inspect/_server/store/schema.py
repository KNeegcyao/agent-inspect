"""SQLite schema 与迁移(MVP 唯一 backend,本地单文件)。

内部实现细节,不进 spec。使用标准库 sqlite3:单写者串行 + WAL,满足"并发分支写入安全"。
"""
from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    agent_name TEXT NOT NULL,
    root_branch_id TEXT,
    lifecycle TEXT NOT NULL,
    parent_trace_id TEXT
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_branch_id TEXT,
    branch_from_step INTEGER NOT NULL,
    origin TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS decision_points (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    input_context_ref TEXT NOT NULL,
    output_ref TEXT,
    output_hash TEXT,
    meta_json TEXT NOT NULL,
    cause_edge_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dp_branch ON decision_points(branch_id, step_index);
CREATE INDEX IF NOT EXISTS idx_dp_trace ON decision_points(trace_id);

CREATE TABLE IF NOT EXISTS blobs (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_diffs (
    id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    diff_against_step INTEGER,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ctx_branch ON context_diffs(branch_id, step_index);

CREATE TABLE IF NOT EXISTS breakpoints (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    kind TEXT,
    agent_id TEXT,
    condition TEXT,
    enabled INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bp_trace ON breakpoints(trace_id);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等迁移:既有库缺列则补列(老行默认为 NULL)。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(traces)").fetchall()}
    if "parent_trace_id" not in cols:
        conn.execute("ALTER TABLE traces ADD COLUMN parent_trace_id TEXT")