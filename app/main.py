"""MPWE 后端入口：启动 FastAPI 服务并托管前端静态资源。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config as app_config
from app.api.auth import create_auth_router
from app.api.routes import create_router
from app.comfyui.client import ComfyUIClient
from app.core.jobs import JobManager
from app.core.queue import JobScheduler
from app.core.vram import VramBudget

logger = logging.getLogger(__name__)

CONFIG = app_config.load_config()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "app" / "webui"


def _build_scheduler(config: dict) -> JobScheduler:
    """构造共享调度器（路由与后台线程共用同一个实例）。"""
    jobs = JobManager(config)
    workers = [
        ComfyUIClient(
            base_url=url,
            timeout=config["comfyui"]["timeout"],
            client_id=config["comfyui"]["client_id"],
        )
        for url in (config["comfyui"].get("workers") or [config["comfyui"]["base_url"]])
    ]
    return JobScheduler(config, jobs, workers, VramBudget(config))


scheduler = _build_scheduler(CONFIG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(
    title="MPWE - Manga Prompt Workflow Engine",
    version="0.2.0",
    lifespan=lifespan,
)
router = create_router(CONFIG, scheduler=scheduler)
auth_router = create_auth_router(CONFIG)
app.include_router(router, prefix="/mpwe")
app.include_router(auth_router, prefix="/mpwe")
# 兼容旧路径：/api 前缀继续可用（新前端统一走 /mpwe，绕开广告拦截器的 /api/ 规则）
app.include_router(router, prefix="/api")
app.include_router(auth_router, prefix="/api")


@app.middleware("http")
async def no_store_api_cache(request, call_next):
    """API 响应一律禁止缓存，避免隧道/浏览器拿到旧状态。"""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        # 页面/静态资源也要求浏览器每次重新校验，避免缓存到旧版本
        response.headers["Cache-Control"] = "no-cache"
    return response


if FRONTEND_DIR.exists():
    # 托管前端 WebUI（前后端代码分离，静态文件由后端统一提供）
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="webui")


def main() -> None:
    host = CONFIG["server"]["host"]
    port = CONFIG["server"]["port"]
    print(f"MPWE 后端已启动: http://{host}:{port}")
    print(f"API 文档: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
