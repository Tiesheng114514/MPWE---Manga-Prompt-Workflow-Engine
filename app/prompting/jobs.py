"""AI 提示词 Agent 的任务管理（内存 + 后台线程，仿 app/core/jobs.py）。"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from app.core import billing
from app.prompting.agent import translate


class PromptJobManager:
    """提示词翻译任务的登记与状态管理（内存实现）。"""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, text: str, model: str, user_id: str) -> dict:
        job = {
            "id": uuid.uuid4().hex[:12],
            "kind": "prompt_translate",
            "user_id": user_id,
            "text": text,
            "model": model,
            "status": "queued",
            "progress": 0,
            "stage": "",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with self._lock:
            self._jobs[job["id"]] = job
        return dict(job)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(fields)
                job["updated_at"] = time.time()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return [dict(j) for j in jobs[:limit]]

    def prune(self, keep: int = 100) -> None:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
            for old in jobs[keep:]:
                self._jobs.pop(old["id"], None)


def _run_prompt_job(jobs: PromptJobManager, job: dict, config: dict) -> None:
    """后台线程：执行两阶段翻译，把进度/结果写回任务。"""
    job_id = job["id"]
    uid = job["user_id"]

    def on_progress(**kw) -> None:
        jobs.update(
            job_id,
            progress=kw.get("value", 0),
            stage=kw.get("note", ""),
        )

    def on_usage(usage: dict) -> None:
        """每次 LLM 调用结束实时扣 API 钱包；余额不足抛错中止流程。"""
        price_info = billing.api_price_info(config)
        billing.charge_api(billing.billing_db(), uid, usage, price_info, ref_id=job_id)

    try:
        jobs.update(job_id, status="running", progress=1, stage="Agent 正在构思…")
        result = translate(
            job["text"],
            model=job["model"],
            on_progress=on_progress,
            on_usage=on_usage,
        )
        if result.get("ok"):
            jobs.update(
                job_id,
                status="done",
                progress=100,
                stage="提示词已生成",
                result={
                    "positive": result.get("positive", ""),
                    "negative": result.get("negative", ""),
                    "brief": result.get("brief", ""),
                    "tuned": bool(result.get("tuned")),
                    "agent_name": result.get("agent_name", ""),
                },
            )
        else:
            jobs.update(job_id, status="error", error=result.get("error") or "未知错误")
    except Exception as exc:
        jobs.update(job_id, status="error", error=f"提示词生成失败：{exc}")


def submit_prompt_job(jobs: PromptJobManager, text: str, model: str = "", user_id: str = "", config: dict | None = None) -> dict:
    """提交一个提示词翻译任务，立即返回任务信息。"""
    job = jobs.create(text, model, user_id)
    thread = threading.Thread(
        target=_run_prompt_job,
        args=(jobs, job, config or {}),
        daemon=True,
    )
    thread.start()
    return job


__all__ = ["PromptJobManager", "submit_prompt_job"]
