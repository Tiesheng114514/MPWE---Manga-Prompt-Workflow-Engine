"""管理员隐私数据：固定盐 + PBKDF2-HMAC-SHA256 密码哈希。

数据保存在 app/隐私数据/secrets.json（.gitignore 已排除，绝不提交）。
盐在安装/首次启动时随机生成后固定；密码由管理员首次启动后台时手动设置。
后续账号体系的数据也放同一目录（用户盐各自随机，管理员固定盐保持不变）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PRIVATE_DIR = PROJECT_ROOT / "app" / "隐私数据"
ITERATIONS = 200000

_lock = threading.Lock()


def private_dir() -> Path:
    """隐私数据目录（可用环境变量 MPWE_PRIVATE_DIR 覆盖，便于测试/部署）。"""
    return Path(os.getenv("MPWE_PRIVATE_DIR") or DEFAULT_PRIVATE_DIR)


def secrets_path() -> Path:
    return private_dir() / "secrets.json"


def load_secrets() -> dict:
    path = secrets_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_secrets(data: dict) -> None:
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _ensure_salt_unlocked() -> Path:
    data = load_secrets()
    admin = data.get("admin") or {}
    if admin.get("salt"):
        return secrets_path()
    admin["salt"] = secrets.token_hex(16)
    admin["iterations"] = ITERATIONS
    admin["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["version"] = 1
    data["admin"] = admin
    save_secrets(data)
    return secrets_path()


def ensure_salt() -> Path:
    """若 secrets.json 不存在则生成安装级固定盐；已存在则保留。返回文件路径。"""
    with _lock:
        return _ensure_salt_unlocked()


def hash_password(password: str, salt_hex: str, iterations: int = ITERATIONS) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def verify_password(password: str) -> bool:
    """校验密码（常量时间比较）。未设置密码/参数非法一律 False。"""
    if not isinstance(password, str) or not password or len(password) > 128:
        return False
    data = load_secrets()
    admin = data.get("admin") or {}
    salt = admin.get("salt") or ""
    stored = admin.get("hash") or ""
    iterations = int(admin.get("iterations") or ITERATIONS)
    if not salt or not stored:
        return False
    calc = hash_password(password, salt, iterations)
    return hmac.compare_digest(calc, stored)


def password_set() -> bool:
    data = load_secrets()
    admin = data.get("admin") or {}
    return bool(admin.get("salt") and admin.get("hash"))


def set_password(password: str) -> None:
    """以固定盐写入新哈希（首次设置与修改共用）。"""
    if not isinstance(password, str) or not password or len(password) < 8 or len(password) > 128:
        raise ValueError("密码长度须为 8-128 位")
    with _lock:
        _ensure_salt_unlocked()
        data = load_secrets()
        admin = data.setdefault("admin", {})
        admin["hash"] = hash_password(
            password,
            admin["salt"],
            int(admin.get("iterations") or ITERATIONS),
        )
        admin["changed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data["admin"] = admin
        save_secrets(data)


__all__ = [
    "private_dir",
    "secrets_path",
    "load_secrets",
    "save_secrets",
    "ensure_salt",
    "hash_password",
    "verify_password",
    "password_set",
    "set_password",
]
