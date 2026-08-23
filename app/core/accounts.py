"""账号体系：用户凭据、邀请码、会话。

数据存 app/隐私数据/accounts.db（.gitignore 已排除，绝不提交）。
密码用 PBKDF2-HMAC-SHA256 + 每用户独立随机盐；用户名明文（管理员后台需要查看）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time

from app.core.db import Database, accounts_db_path, row_to_dict, rows_to_dicts

ITERATIONS = 200000
SESSION_TTL = 30 * 24 * 3600  # 30 天自动登录

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid           TEXT PRIMARY KEY,              -- 00001 起递增，>99999 继续往后
    username      TEXT NOT NULL UNIQUE,
    salt          TEXT NOT NULL,
    hash          TEXT NOT NULL,
    iterations    INTEGER NOT NULL DEFAULT 200000,
    invite_code   TEXT,
    status        TEXT NOT NULL DEFAULT 'active', -- active / disabled
    created_at    REAL NOT NULL,
    last_login_at REAL
);

CREATE TABLE IF NOT EXISTS invite_codes (
    code         TEXT PRIMARY KEY,
    max_invites  INTEGER NOT NULL,
    used_count   INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

_init_lock = threading.Lock()
_db: Database | None = None

USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff]{2,32}$")


def accounts_db() -> Database:
    global _db
    with _init_lock:
        if _db is None:
            _db = Database(accounts_db_path())
            _db.init(_SCHEMA)
        return _db


def hash_password(password: str, salt_hex: str, iterations: int = ITERATIONS) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def validate_username(username: str) -> str | None:
    """返回错误信息；None 表示合法。"""
    if not username or not USERNAME_RE.match(username):
        return "用户名须为 2-32 位中英文/数字/下划线。"
    return None


def validate_password(password: str) -> str | None:
    if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
        return "密码长度须为 8-128 位。"
    return None


# ---------------- 用户 ID（00001 起递增，>99999 继续往后） ----------------


def _next_uid_on(conn) -> str:
    """在同一连接内分配下一个用户 ID（须在事务中调用）。"""
    row = conn.execute("SELECT MAX(CAST(uid AS INTEGER)) AS m FROM users").fetchone()
    nxt = int(row["m"]) + 1 if row and row["m"] is not None else 1
    while True:
        uid = f"{nxt:05d}"
        if not conn.execute("SELECT 1 FROM users WHERE uid = ?", (uid,)).fetchone():
            return uid
        nxt += 1


def next_uid(db: Database) -> str:
    with db.conn() as conn:
        return _next_uid_on(conn)


# ---------------- 用户 ----------------


def create_user(db: Database, username: str, password: str, invite_code: str = "") -> dict:
    """创建用户：校验邀请码并原子占位 → 插入用户。返回用户 dict。"""
    err = validate_username(username)
    if err:
        raise ValueError(err)
    err = validate_password(password)
    if err:
        raise ValueError(err)
    code = (invite_code or "").strip()
    with db.conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if code:
            cur = conn.execute(
                "UPDATE invite_codes SET used_count = used_count + 1 "
                "WHERE code = ? AND used_count < max_invites",
                (code,),
            )
            if cur.rowcount == 0:
                raise ValueError("邀请码无效或已用完。")
        uid = _next_uid_on(conn)
        salt = secrets.token_hex(16)
        try:
            conn.execute(
                "INSERT INTO users (uid, username, salt, hash, iterations, invite_code, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                (uid, username, salt, hash_password(password, salt), ITERATIONS, code or None, time.time()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("用户名已存在，请换一个。") from None
    return get_user_by_username(db, username)  # type: ignore[return-value]


def get_user_by_username(db: Database, username: str) -> dict | None:
    with db.conn() as conn:
        return row_to_dict(
            conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        )


def get_user(db: Database, uid: str) -> dict | None:
    with db.conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE uid = ?", (uid,)).fetchone())


def list_users(db: Database) -> list[dict]:
    with db.conn() as conn:
        return rows_to_dicts(
            conn.execute("SELECT * FROM users ORDER BY CAST(uid AS INTEGER)").fetchall()
        )


def verify_login(db: Database, username: str, password: str) -> dict | None:
    user = get_user_by_username(db, username)
    if not user:
        return None
    calc = hash_password(password, user["salt"], int(user["iterations"] or ITERATIONS))
    if not hmac.compare_digest(calc, user["hash"]):
        return None
    if user["status"] != "active":
        return None
    with db.conn() as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE uid = ?", (time.time(), user["uid"]))
    return user


def set_user_status(db: Database, uid: str, status: str) -> None:
    if status not in ("active", "disabled"):
        raise ValueError("状态只能是 active / disabled")
    with db.conn() as conn:
        conn.execute("UPDATE users SET status = ? WHERE uid = ?", (status, uid))


def reset_password(db: Database, uid: str, new_password: str) -> None:
    err = validate_password(new_password)
    if err:
        raise ValueError(err)
    salt = secrets.token_hex(16)
    with db.conn() as conn:
        conn.execute(
            "UPDATE users SET salt = ?, hash = ?, iterations = ? WHERE uid = ?",
            (salt, hash_password(new_password, salt), ITERATIONS, uid),
        )


def delete_user(db: Database, uid: str) -> None:
    """删除用户（仅本地维护用，谨慎调用）。"""
    with db.conn() as conn:
        conn.execute("DELETE FROM users WHERE uid = ?", (uid,))


# ---------------- 邀请码 ----------------


def create_invite_codes(db: Database, code_specs: list[tuple[str, int]]) -> list[dict]:
    """批量创建邀请码。code_specs: [(码, 最大可邀请人数), ...]。"""
    created = []
    with db.conn() as conn:
        for raw_code, max_invites in code_specs:
            code = (raw_code or "").strip()
            if not code:
                raise ValueError("邀请码不能为空。")
            try:
                max_invites = int(max_invites)
            except (TypeError, ValueError):
                raise ValueError(f"邀请码 {code} 的可邀请人数必须是整数。") from None
            if max_invites < 1:
                raise ValueError(f"邀请码 {code} 的可邀请人数至少为 1。")
            if conn.execute("SELECT 1 FROM invite_codes WHERE code = ?", (code,)).fetchone():
                raise ValueError(f"邀请码 {code} 已存在。")
            conn.execute(
                "INSERT INTO invite_codes (code, max_invites, used_count, created_at) VALUES (?, ?, 0, ?)",
                (code, max_invites, time.time()),
            )
            created.append({"code": code, "max_invites": max_invites, "used_count": 0})
    return created


def list_invite_codes(db: Database) -> list[dict]:
    with db.conn() as conn:
        return rows_to_dicts(
            conn.execute("SELECT * FROM invite_codes ORDER BY created_at DESC").fetchall()
        )


def delete_invite_code(db: Database, code: str) -> None:
    """删除邀请码；只要有人用它注册过就不能删。"""
    with db.conn() as conn:
        row = conn.execute("SELECT used_count FROM invite_codes WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise KeyError("邀请码不存在")
        if int(row["used_count"]) > 0:
            raise ValueError("该邀请码已有用户注册，不能删除。")
        conn.execute("DELETE FROM invite_codes WHERE code = ?", (code,))


# ---------------- 会话（HttpOnly cookie，30 天自动登录） ----------------


def create_session(db: Database, uid: str) -> str:
    token = secrets.token_urlsafe(32)
    with db.conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, uid, time.time(), time.time() + SESSION_TTL),
        )
    return token


def session_user(db: Database, token: str | None) -> dict | None:
    if not token:
        return None
    with db.conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token = ? AND expires_at > ?",
            (token, time.time()),
        ).fetchone()
        if row is None:
            return None
        return row_to_dict(
            conn.execute("SELECT * FROM users WHERE uid = ?", (row["user_id"],)).fetchone()
        )


def delete_session(db: Database, token: str | None) -> None:
    if not token:
        return
    with db.conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


__all__ = [
    "accounts_db",
    "create_invite_codes",
    "create_session",
    "create_user",
    "delete_invite_code",
    "delete_session",
    "delete_user",
    "get_user",
    "get_user_by_username",
    "hash_password",
    "list_invite_codes",
    "list_users",
    "reset_password",
    "session_user",
    "set_user_status",
    "verify_login",
]
