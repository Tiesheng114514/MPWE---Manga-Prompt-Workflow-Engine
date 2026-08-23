"""命令行修改管理密码。

用法：.venv\\Scripts\\python.exe -m app.admin.changepwd
（由 scripts\\修改管理员密码.bat 调用）
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.admin import secrets_store  # noqa: E402


def _prompt(hint: str) -> str:
    # 本地工具，密码明文可见输入即可，不做掩码
    return input(hint).strip()


def main() -> None:
    secrets_store.ensure_salt()
    if not secrets_store.password_set():
        print("尚未设置管理密码，请先运行 scripts\\启动管理员后台WebUI.bat 完成首次设置。")
        return
    old = _prompt("原管理密码：")
    if not secrets_store.verify_password(old):
        print("原密码错误。")
        return
    while True:
        p1 = _prompt("新管理密码（8-128 位）：")
        p2 = _prompt("再次输入确认：")
        if p1 and p1 == p2 and len(p1) >= 8:
            try:
                secrets_store.set_password(p1)
            except ValueError as exc:
                print(f"  {exc}，请重试。")
                continue
            print("管理密码已更新。")
            return
        print("两次输入不一致、为空或长度不足 8 位，请重试。")


if __name__ == "__main__":
    main()
