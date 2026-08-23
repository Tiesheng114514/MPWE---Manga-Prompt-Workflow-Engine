"""管理员会话（内存实现，8 小时；服务重启后需重新登录）。"""

from __future__ import annotations

import secrets
import threading
import time

SESSION_TTL = 8 * 3600

_sessions: dict[str, float] = {}
_lock = threading.Lock()


def create_session() -> str:
    token = secrets.token_urlsafe(24)
    with _lock:
        _sessions[token] = time.time() + SESSION_TTL
    return token


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        exp = _sessions.get(token)
        if exp is None:
            return False
        if exp < time.time():
            _sessions.pop(token, None)
            return False
        return True


def invalidate(token: str | None) -> None:
    if not token:
        return
    with _lock:
        _sessions.pop(token, None)


__all__ = ["SESSION_TTL", "create_session", "session_valid", "invalidate"]
