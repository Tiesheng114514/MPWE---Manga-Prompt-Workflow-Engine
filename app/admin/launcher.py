"""启动管理员后台：首次运行手动设置管理密码，然后启动/打开 WebUI。

用法：.venv\\Scripts\\python.exe -m app.admin.launcher
（由 scripts\\启动管理员后台WebUI.bat 调用）
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.admin import secrets_store  # noqa: E402


def _prompt(hint: str) -> str:
    # 本地工具，密码明文可见输入即可，不做掩码
    return input(hint).strip()


def ensure_password() -> None:
    """确保隐私数据与固定盐存在；首次运行由管理员手动设置密码。"""
    secrets_store.ensure_salt()
    if secrets_store.password_set():
        return
    print("=" * 56)
    print("  首次使用管理员后台：请设置管理密码（8-128 位）")
    print("  （密码只保存在本机 app/隐私数据/secrets.json，不会提交到 GitHub）")
    print("=" * 56)
    while True:
        p1 = _prompt("  设置管理密码：")
        p2 = _prompt("  再次输入确认：")
        if p1 and p1 == p2 and len(p1) >= 8:
            try:
                secrets_store.set_password(p1)
            except ValueError as exc:
                print(f"  {exc}，请重试。")
                continue
            print("  管理密码已设置。\n")
            return
        print("  两次输入不一致、为空或长度不足 8 位，请重试。")


def _webui_up(host: str, port: int) -> bool:
    try:
        # 管理服务是独立 FastAPI（app/admin_server.py），用 /api/session 探测
        with urllib.request.urlopen(f"http://{host}:{port}/api/session", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    ensure_password()
    host = os.getenv("MPWE_ADMIN_HOST", "127.0.0.1")
    port = int(os.getenv("MPWE_ADMIN_PORT", "8643"))
    admin_url = f"http://{host}:{port}/"
    if _webui_up(host, port):
        print(f"管理员后台已在运行，打开：{admin_url}")
        webbrowser.open(admin_url)
        return
    print(f"正在启动管理员后台（独立端口 {port}）…")

    def _open_admin_later() -> None:
        time.sleep(3)
        try:
            webbrowser.open(admin_url)
        except Exception:
            pass

    threading.Thread(target=_open_admin_later, daemon=True).start()

    import uvicorn

    uvicorn.run("app.admin_server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
