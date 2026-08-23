"""初始化隐私数据目录与固定盐（幂等，可重复执行）。

生成 app/隐私数据/secrets.json（含安装级固定盐）。
若文件已存在则跳过，绝不覆盖，避免重置已有管理密码。
管理员密码不在这里生成：由「启动管理员后台WebUI」首次运行时手动设置。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.admin import secrets_store  # noqa: E402


def main() -> None:
    path = secrets_store.ensure_salt()
    print(f"隐私数据已就绪: {path}")


if __name__ == "__main__":
    main()
