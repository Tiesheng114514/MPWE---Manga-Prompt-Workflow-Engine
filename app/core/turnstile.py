"""Cloudflare Turnstile 人机验证（服务端 siteverify）。"""

from __future__ import annotations

import socket
import threading
import uuid

import requests

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_SOCKET_LOCK = threading.Lock()


class TurnstileError(RuntimeError):
    """验证服务异常（网络错误等），不是"验证失败"。"""


def _post_siteverify(payload: dict, timeout: float = 12.0):
    """IPv4 优先的 siteverify 请求。

    本机 DNS 会先返回 AAAA（IPv6），而 IPv6 路由不可用，直接 POST 会挂到超时；
    这里临时让 getaddrinfo 优先返回 IPv4（仅在本调用期间，带锁保护）。
    """
    original = socket.getaddrinfo

    def _v4_first(host, port, family=0, type=0, proto=0, flags=0):
        result = original(host, port, family, type, proto, flags)
        v4 = [r for r in result if r[0] == socket.AF_INET]
        return v4 or result

    with _SOCKET_LOCK:
        socket.getaddrinfo = _v4_first
        try:
            return requests.post(SITEVERIFY_URL, json=payload, timeout=timeout)
        finally:
            socket.getaddrinfo = original


def verify_token(config: dict, token: str, remote_ip: str = "") -> bool:
    """校验前端提交的 Turnstile token。

    - turnstile.enabled=False 时直接放行（本地联调用）；
    - token 缺失/过期/重复使用都返回 False；
    - 网络异常抛 TurnstileError，由调用方决定策略。
    """
    turnstile = config.get("turnstile") or {}
    if not turnstile.get("enabled", True):
        return True
    secret = (turnstile.get("secret_key") or "").strip()
    if not secret:
        raise TurnstileError("Turnstile 未配置 Secret Key（请检查 .env 的 TURNSTILE_SECRET_KEY）")
    if not token:
        return False
    payload: dict = {
        "secret": secret,
        "response": token,
        "idempotency_key": str(uuid.uuid4()),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip
    last_exc: Exception | None = None
    for _attempt in range(2):
        try:
            resp = _post_siteverify(payload, timeout=12.0)
            data = resp.json()
            return bool(data.get("success"))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise TurnstileError(f"Turnstile 验证服务异常: {last_exc}") from last_exc


__all__ = ["TurnstileError", "verify_token"]
