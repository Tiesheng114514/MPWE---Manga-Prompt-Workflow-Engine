"""SQLite 数据库助手：按连接打开/关闭，行返回 dict，WAL 模式。

两个库分工：
  - app/隐私数据/accounts.db：账号凭据、邀请码、会话（不提交 git）
  - data/mpwe.db：任务、图片元数据、钱包、账单、算力统计（不提交 git）
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.admin.secrets_store import private_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def accounts_db_path() -> Path:
    return private_dir() / "accounts.db"


def mpwe_db_path() -> Path:
    override = os.getenv("MPWE_DB_PATH", "").strip()
    return Path(override) if override else PROJECT_ROOT / "data" / "mpwe.db"


# data/mpwe.db 全部表结构：钱包、账单、任务、任务图片（幂等建表）
MPWE_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    user_id           TEXT PRIMARY KEY,
    api_balance_mli   INTEGER NOT NULL DEFAULT 0,
    image_balance_mli INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS billing_entries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    kind              TEXT NOT NULL,
    amount_mli        INTEGER NOT NULL,
    balance_after_mli INTEGER NOT NULL,
    ref_type          TEXT,
    ref_id            TEXT,
    detail            TEXT,
    created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_user ON billing_entries(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_entries_kind ON billing_entries(kind, created_at);

CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    prompt_id           TEXT,
    workflow            TEXT NOT NULL,
    params              TEXT NOT NULL,
    status              TEXT NOT NULL,
    progress            INTEGER NOT NULL DEFAULT 0,
    stage               TEXT NOT NULL DEFAULT '',
    error               TEXT,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    started_at          REAL,
    finished_at         REAL,
    gpu_seconds         REAL,
    gpu_flops_estimate  REAL,
    priority            INTEGER NOT NULL DEFAULT 0,
    worker_url          TEXT,
    reserved_mb         INTEGER,
    attempts            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_time ON jobs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS job_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    filename    TEXT NOT NULL,
    subfolder   TEXT NOT NULL DEFAULT '',
    image_type  TEXT NOT NULL DEFAULT 'output',
    local_path  TEXT,
    width       INTEGER,
    height      INTEGER,
    created_at  REAL NOT NULL,
    UNIQUE(job_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_images_job ON job_images(job_id, seq);
"""


def init_mpwe_db() -> Database:
    """初始化业务库（幂等），返回单例之外的独立实例。"""
    db = Database(mpwe_db_path())
    db.init(MPWE_SCHEMA)
    with db.conn() as conn:
        _ensure_jobs_columns(conn)
    return db


def _ensure_jobs_columns(conn: sqlite3.Connection) -> None:
    """老库迁移：jobs 表补充排队系统字段（已存在则跳过）。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    additions = {
        "priority": "INTEGER NOT NULL DEFAULT 0",
        "worker_url": "TEXT",
        "reserved_mb": "INTEGER",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, ddl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def conn(self) -> sqlite3.Connection:
        """每次操作独立连接，提交后关闭（线程安全，简单可靠）。"""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self, schema_sql: str) -> None:
        with self.conn() as conn:
            conn.executescript(schema_sql)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


__all__ = [
    "Database",
    "MPWE_SCHEMA",
    "accounts_db_path",
    "init_mpwe_db",
    "mpwe_db_path",
    "row_to_dict",
    "rows_to_dicts",
]
