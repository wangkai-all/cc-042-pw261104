"""SQLite 存储层：schema 与连接辅助。"""
from __future__ import annotations

import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

-- 一轮采集 = 一个批次。只有整轮成功(status='success')才会成为页面当前结果。
CREATE TABLE IF NOT EXISTS batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     INTEGER NOT NULL REFERENCES repos(id),
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    status      TEXT NOT NULL DEFAULT 'running',  -- running | success | failed
    error       TEXT
);

-- 提交按仓库全局去重保存：共享提交只存一份，删分支不会删掉其他分支引用的数据。
CREATE TABLE IF NOT EXISTS commits (
    repo_id        INTEGER NOT NULL REFERENCES repos(id),
    sha            TEXT NOT NULL,
    message        TEXT NOT NULL,
    author_name    TEXT NOT NULL,
    author_email   TEXT NOT NULL,
    author_time    INTEGER NOT NULL,
    author_tz      TEXT NOT NULL,
    committer_name TEXT NOT NULL,
    committer_email TEXT NOT NULL,
    committer_time INTEGER NOT NULL,
    committer_tz   TEXT NOT NULL,
    collected_at   INTEGER NOT NULL,
    PRIMARY KEY (repo_id, sha)
);

CREATE TABLE IF NOT EXISTS commit_parents (
    repo_id    INTEGER NOT NULL,
    sha        TEXT NOT NULL,
    parent_sha TEXT NOT NULL,
    position   INTEGER NOT NULL,
    PRIMARY KEY (repo_id, sha, position)
);

-- 每个提交相对第一父提交(根提交相对空树)的文件变更；改名保留新旧两个名字。
CREATE TABLE IF NOT EXISTS commit_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     INTEGER NOT NULL,
    sha         TEXT NOT NULL,
    path        TEXT NOT NULL,
    old_path    TEXT,
    change_type TEXT NOT NULL,           -- A | M | D | R
    additions   INTEGER,                 -- 二进制为 NULL
    deletions   INTEGER,                 -- 二进制为 NULL
    is_binary   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_commit_files_sha ON commit_files(repo_id, sha);

-- 每轮采集开始时记录的分支快照；status: new|same|forward|rewritten|deleted
CREATE TABLE IF NOT EXISTS batch_branches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        INTEGER NOT NULL REFERENCES batches(id),
    name            TEXT NOT NULL,
    tip_sha         TEXT,
    prev_tip_sha    TEXT,
    status          TEXT NOT NULL,
    reachable_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_batch_branches ON batch_branches(batch_id);

-- 每个批次里各分支能到达的提交集合（改写后会按新指向重新计算）。
CREATE TABLE IF NOT EXISTS batch_branch_commits (
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    branch   TEXT NOT NULL,
    sha      TEXT NOT NULL,
    PRIMARY KEY (batch_id, branch, sha)
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class Database:
    """保存路径，按需开连接（WAL 下读写可并发）；写锁用于串行化写操作。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        init_db(connect(db_path))
        self.write_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        return connect(self.db_path)
