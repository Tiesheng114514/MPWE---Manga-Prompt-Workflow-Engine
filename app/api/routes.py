"""REST API 路由：前端 WebUI 与后端之间的唯一通信入口。

每个接口都对应一个明确的功能，新增功能时在下方添加路由即可。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.api.auth import current_user
from app.comfyui import workflows
from app.comfyui.client import ComfyUIClient, ComfyUIError
from app.comfyui.presets import CHECKPOINT_PRESETS, DIFFUSION_PRESETS
from app.core import billing
from app.core.jobs import JobManager
from app.core.queue import JobScheduler
from app.core.schemas import GenerateRequest, PromptTranslateRequest
from app.core.vram import VramBudget
from app.prompting import loader as prompt_loader
from app.prompting.jobs import PromptJobManager, submit_prompt_job


def create_router(config: dict, scheduler: JobScheduler | None = None) -> APIRouter:
    """根据配置创建路由（依赖注入：ComfyUI 客户端 + 任务管理器）。"""
    workers = [
        ComfyUIClient(
            base_url=url,
            timeout=config["comfyui"]["timeout"],
            client_id=config["comfyui"]["client_id"],
        )
        for url in (config["comfyui"].get("workers") or [config["comfyui"]["base_url"]])
    ]
    client = workers[0]
    jobs = JobManager(config)
    vram = VramBudget(config)
    if scheduler is None:
        scheduler = JobScheduler(config, jobs, workers, vram)
    prompt_jobs = PromptJobManager()
    router = APIRouter()

    # ---------------- 基础 ----------------
    @router.get("/health")
    def health() -> dict:
        """后端健康状态 + ComfyUI 连接状态。"""
        return {
            "status": "ok",
            "comfyui_connected": any(w.check_connection() for w in workers),
            "comfyui_base_url": client.base_url,
            "comfyui_workers": [w.base_url for w in workers],
            "time": time.time(),
        }

    @router.get("/config")
    def get_config() -> dict:
        """返回运行配置（不含敏感信息；Turnstile site key 是公开的）。"""
        return {
            "server": config["server"],
            "comfyui": {"base_url": client.base_url},
            "turnstile": {
                "enabled": bool((config.get("turnstile") or {}).get("enabled", True)),
                "site_key": (config.get("turnstile") or {}).get("site_key", ""),
            },
            "billing": {
                "image_price_per_image": (config.get("billing") or {}).get("image", {}).get("price_per_image", 0.3),
                "signup_bonus": (config.get("billing") or {}).get("signup_bonus") or {},
                "free_recharge": (config.get("billing") or {}).get("free_recharge") or {},
            },
        }

    # ---------------- ComfyUI 状态与枚举 ----------------
    @router.get("/comfyui/status")
    def comfyui_status() -> dict:
        try:
            return client.get_system_stats()
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/comfyui/models")
    def comfyui_models(category: str = Query("checkpoints")) -> dict:
        try:
            return {"category": category, "models": client.list_models(category)}
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/comfyui/samplers")
    def comfyui_samplers() -> dict:
        try:
            return {"samplers": client.list_samplers()}
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/comfyui/schedulers")
    def comfyui_schedulers() -> dict:
        try:
            return {"schedulers": client.list_schedulers()}
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/comfyui/clip_types")
    def comfyui_clip_types() -> dict:
        try:
            return {"clip_types": client.list_clip_types()}
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/comfyui/diffusion_presets")
    def comfyui_diffusion_presets() -> dict:
        """扩散模型官方预设（VAE / 文本编码器 / CLIP 类型 / 推荐参数）。"""
        return {"presets": DIFFUSION_PRESETS}

    @router.get("/comfyui/checkpoint_presets")
    def comfyui_checkpoint_presets() -> dict:
        """Checkpoint 模型官方预设（步数 / CFG / 采样器等推荐参数）。"""
        return {"presets": CHECKPOINT_PRESETS}

    @router.get("/comfyui/workflows")
    def comfyui_workflows() -> dict:
        """列出当前已注册的所有工作流功能。"""
        return {"workflows": workflows.list_workflows()}

    # ---------------- 生成任务 ----------------
    @router.post("/generate")
    def generate(req: GenerateRequest, request: Request) -> dict:
        """提交一个生成任务（立即返回，后台轮询结果）。"""
        user = current_user(request)
        params: dict[str, Any] = req.model_dump()
        try:
            # 余额预检：图片钱包至少够本次预期张数（0.3 元/张）
            price = float((config.get("billing") or {}).get("image", {}).get("price_per_image", 0.3))
            expected = max(1, int(params.get("batch_size") or 1))
            required_mli = round(price * 1000) * expected
            wallet = billing.get_wallets(billing.billing_db(), user["uid"])
            if int(wallet["image_balance_mli"]) < required_mli:
                raise HTTPException(
                    status_code=402,
                    detail=f"图片钱包余额不足（需 ≥{required_mli / 1000:.3f} 金币，当前 {wallet['image_balance_mli'] / 1000:.3f} 金币），请先在管理后台充值或领取免费额度。",
                )
            peak = vram.job_peak_mb(params, req.workflow)
            job = jobs.enqueue(req.workflow, params, user["uid"], reserved_mb=peak)
            scheduler.wake()
            jobs.prune()
            return job
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/jobs")
    def list_jobs(request: Request, limit: int = 50) -> dict:
        """列出当前用户最近的生成任务（仅本人数据）。"""
        user = current_user(request)
        return {"jobs": jobs.list(limit, user_id=user["uid"])}

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict:
        """查询单个任务的状态与结果。"""
        user = current_user(request)
        job = jobs.get(job_id)
        if job is None or job["user_id"] != user["uid"]:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request) -> dict:
        """取消排队/运行中的生成任务（只影响该任务所在实例，不做全局中断）。"""
        user = current_user(request)
        job = jobs.get(job_id)
        if job is None or job["user_id"] != user["uid"]:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job["status"] not in ("queued", "running"):
            return {"ok": True, "status": job["status"]}
        jobs.cancel(job_id)
        worker = scheduler.client_for(job.get("worker_url") or "") if job.get("worker_url") else None
        if worker and job.get("prompt_id"):
            try:
                worker.cancel_prompt(job["prompt_id"])
            except ComfyUIError:
                pass
        return {"ok": True, "status": "canceled"}

    @router.get("/queue")
    def queue_status() -> dict:
        """GPU 队列状态（运行中/排队数/预算/实例），前端轮询展示。"""
        return scheduler.stats()

    @router.get("/jobs/{job_id}/images/{index}")
    def get_job_image(job_id: str, index: int, request: Request) -> Response:
        """返回任务输出图片：优先本地缓存文件，缺失时回退 ComfyUI 代理。"""
        user = current_user(request)
        job = jobs.get(job_id)
        if job is None or job["user_id"] != user["uid"]:
            raise HTTPException(status_code=404, detail="任务不存在")
        images = job.get("images") or []
        if index < 0 or index >= len(images):
            raise HTTPException(status_code=404, detail="图片不存在")
        image = images[index]
        headers = {"Cache-Control": "public, max-age=86400"}
        local_path = image.get("local_path")
        if local_path and Path(local_path).exists():
            stat = Path(local_path).stat()
            headers["ETag"] = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            return Response(
                content=Path(local_path).read_bytes(),
                media_type="image/png",
                headers=headers,
            )
        try:
            data = client.get_image(
                filename=image["filename"],
                subfolder=image.get("subfolder", ""),
                image_type=image.get("type", "output"),
            )
        except ComfyUIError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(content=data, media_type="image/png", headers=headers)

    # ---------------- AI 提示词 Agent ----------------
    @router.get("/prompt/agents")
    def prompt_agents() -> dict:
        """列出已配置专属翻译 Agent 的模型（一个模型对应一个 Agent）。"""
        return {"agents": prompt_loader.get_supported_agents()}

    @router.post("/prompt/translate")
    def prompt_translate(req: PromptTranslateRequest, request: Request) -> dict:
        """提交一个提示词翻译任务（立即返回，后台轮询结果）。"""
        user = current_user(request)
        text = (req.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="描述不能为空。")
        model = (req.model or "").strip()
        if model not in prompt_loader.get_supported_agents():
            raise HTTPException(
                status_code=400,
                detail="该模型暂无适配的 AI 提示词 Agent（一个模型对应一个 Agent），可在 agent_prompts.yaml 的 models 下新增配置。",
            )
        wallet = billing.get_wallets(billing.billing_db(), user["uid"])
        if int(wallet["api_balance_mli"]) <= 0:
            raise HTTPException(status_code=402, detail="API 钱包（银币）余额不足，请先在管理后台充值或领取免费额度。")
        job = submit_prompt_job(prompt_jobs, text, model, user["uid"], config)
        prompt_jobs.prune()
        return {"job_id": job["id"]}

    @router.get("/prompt/jobs/{job_id}")
    def get_prompt_job(job_id: str, request: Request) -> dict:
        """查询提示词翻译任务的状态与结果。"""
        user = current_user(request)
        job = prompt_jobs.get(job_id)
        if job is None or job.get("user_id") != user["uid"]:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job

    return router
