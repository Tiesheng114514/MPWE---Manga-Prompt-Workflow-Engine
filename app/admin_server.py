"""管理员后台独立服务（默认端口 8643）。

与公网 WebUI（8642）完全分离：只挂载管理路由与必要的静态资源，
不包含任何生图接口。启动方式：
    .venv\\Scripts\\python.exe -m app.admin_server
（通常由 scripts\\启动管理员后台WebUI.bat 调用）
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config as app_config
from app.admin.routes import create_admin_router

CONFIG = app_config.load_config()
WEBUI_DIR = Path(__file__).resolve().parent / "webui"

app = FastAPI(title="MPWE 管理员后台", version="0.1.0")
app.include_router(create_admin_router(CONFIG))

if WEBUI_DIR.exists():
    # 管理页用到的公共静态资源（css / js）单独托管；
    # 页面本身由路由返回（admin_login.html / admin.html）。
    if (WEBUI_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=str(WEBUI_DIR / "css")), name="admin_css")
    if (WEBUI_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=str(WEBUI_DIR / "js")), name="admin_js")


def main() -> None:
    host = CONFIG["admin"]["host"]
    port = CONFIG["admin"]["port"]
    print(f"管理员后台已启动: http://{host}:{port}（仅本机访问，勿暴露公网）")
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
