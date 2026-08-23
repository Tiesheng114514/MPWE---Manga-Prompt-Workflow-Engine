"""任务调度器：持久化队列 + 显存预算准入 + 多 ComfyUI 实例分发。

设计（结合老项目 VramScheduler 的思路与实测教训）：
  - 任务先落库（status=queued），由本调度器按 优先级 + 创建时间 领取；
  - 领取前做两道检查：每用户并发上限 + 显存预算（同时运行任务峰值之和 <= 容量）；
  - 并行 = 多个 ComfyUI 实例，每个实例同时只跑 1 个任务（ComfyUI 单进程单卡的硬限制）；
  - 大任务占满预算时，放不下的小任务可以让位等待（防饿死由预算自然保证）；
  - 实例提交失败会被临时拉黑（worker_down_grace_s），任务保留排队重试；
  - 服务重启：残留 running 任务标记失败，并把对应 ComfyUI prompt 移出队列。
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.comfyui import workflows
from app.comfyui.client import ComfyUIClient, ComfyUIError
from app.core.jobs import JobManager, _run_polling
from app.core.vram import VramBudget

logger = logging.getLogger(__name__)


def build_graph_for_worker(jobs: JobManager, client: ComfyUIClient, workflow_name: str, params: dict) -> dict:
    """在领取时刻重建工作流图（quality_pass 先把源图上传到目标实例）。"""
    graph_params = {k: v for k, v in params.items() if k != "workflow"}
    if workflow_name == "quality_pass":
        source = graph_params.pop("image_filename", "")
        subfolder = graph_params.pop("image_subfolder", "")
        image_type = graph_params.pop("image_type", "output")
        if not source:
            raise ValueError("quality_pass 需要 image_filename（已生成图片的文件名）")
        image_bytes = _load_source_image_bytes(jobs, client, source, subfolder, image_type)
        uploaded = client.upload_image(image_bytes, source)
        graph_params["image_filename"] = uploaded.get("name") or source
    return workflows.build_workflow(workflow_name, **graph_params)


def _load_source_image_bytes(
    jobs: JobManager,
    client: ComfyUIClient,
    filename: str,
    subfolder: str,
    image_type: str,
) -> bytes:
    """优先本地缓存（多实例下源图可能落在别的实例），缺失再向 ComfyUI 拉取。"""
    try:
        with jobs.db.conn() as conn:
            row = conn.execute(
                "SELECT local_path FROM job_images WHERE filename = ? ORDER BY id DESC LIMIT 1",
                (filename,),
            ).fetchone()
        if row and row["local_path"] and Path(row["local_path"]).exists():
            return Path(row["local_path"]).read_bytes()
    except Exception:
        pass
    return client.get_image(filename, subfolder, image_type)


class JobScheduler:
    """后台调度线程：从 SQLite 队列领取任务，按预算分发到 ComfyUI 实例。"""

    def __init__(
        self,
        config: dict,
        jobs: JobManager,
        workers: list[ComfyUIClient],
        vram: VramBudget | None = None,
    ) -> None:
        self.config = config
        self.jobs = jobs
        self.workers = workers
        self.vram = vram or VramBudget(config)
        queue_cfg = config.get("queue") or {}
        self.max_concurrent_per_user = max(1, int(queue_cfg.get("max_concurrent_per_user", 2)))
        self.poll_interval_s = max(0.1, float(queue_cfg.get("poll_interval_s", 0.5)))
        self.dispatch_limit = max(1, int(queue_cfg.get("max_queue_dispatch", 50)))
        self.worker_down_grace_s = max(0.0, float(queue_cfg.get("worker_down_grace_s", 30)))
        self.max_dispatch_attempts = max(1, int(queue_cfg.get("max_dispatch_attempts", 3)))

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._rr = itertools.count()
        self._worker_down_until: dict[str, float] = {}
        self._poll_threads: dict[str, threading.Thread] = {}

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        """启动调度线程；同时恢复重启前的残留任务。"""
        if self._thread and self._thread.is_alive():
            return
        stray = self.jobs.list_running()
        recovered = self.jobs.restart_recover()
        for job in stray:
            if job.get("prompt_id") and job.get("worker_url"):
                client = self.client_for(job["worker_url"])
                if client is not None:
                    try:
                        client.cancel_prompt(job["prompt_id"])
                    except ComfyUIError:
                        pass
        if recovered:
            logger.warning("重启恢复：%d 个运行中任务已标记失败", recovered)
        self._thread = threading.Thread(
            target=self._loop, name="mpwe-job-scheduler", daemon=True
        )
        self._thread.start()
        logger.info("任务调度器已启动（workers=%s）", [w.base_url for w in self.workers])

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def wake(self) -> None:
        """新任务入队后立即唤醒调度（无需等 poll_interval）。"""
        self._wake.set()

    # ---------------- 主循环 ----------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("调度器 tick 异常")
            self._wake.wait(self.poll_interval_s)
            self._wake.clear()

    def _tick(self) -> None:
        with self._lock:
            running = self.jobs.list_running()
            busy_worker: dict[str, str] = {}
            reserved = 0
            user_running: dict[str, int] = defaultdict(int)
            for job in running:
                if job.get("worker_url"):
                    busy_worker[job["worker_url"]] = job["id"]
                reserved += int(job.get("reserved_mb") or 0)
                user_running[job["user_id"]] += 1

            for job in self.jobs.list_queued(limit=self.dispatch_limit):
                if self._stop.is_set():
                    return
                uid = job["user_id"]
                if user_running[uid] >= self.max_concurrent_per_user:
                    continue
                cost = max(1, int(job.get("reserved_mb") or 0))
                worker = self._pick_worker(busy_worker, reserved, cost)
                if worker is None:
                    continue  # 无空闲槽位或预算不足，等下一轮
                try:
                    prompt_id = self._dispatch(job, worker)
                except ValueError as exc:
                    self.jobs.fail(job["id"], str(exc))
                    continue
                except ComfyUIError as exc:
                    self._mark_worker_down(worker)
                    attempts = self.jobs.bump_attempts(job["id"])
                    if attempts >= self.max_dispatch_attempts:
                        self.jobs.fail(job["id"], f"连续提交失败（{worker.base_url}）: {exc}")
                    else:
                        logger.warning("任务 %s 提交失败将重试（第 %d 次）: %s", job["id"], attempts, exc)
                    continue
                self.jobs.claim(job["id"], worker.base_url, prompt_id, cost)
                busy_worker[worker.base_url] = job["id"]
                reserved += cost
                user_running[uid] += 1
                self._start_polling(job["id"], worker)

    # ---------------- 实例选择与提交 ----------------
    def _pick_worker(
        self,
        busy_worker: dict[str, str],
        reserved: int,
        cost: int,
    ) -> ComfyUIClient | None:
        now = time.time()
        free = [
            w
            for w in self.workers
            if w.base_url not in busy_worker
            and now >= self._worker_down_until.get(w.base_url, 0.0)
        ]
        if not free:
            return None
        fit = [w for w in free if self.vram.fits(reserved, cost)]
        if not fit:
            return None
        return fit[next(self._rr) % len(fit)]

    def _dispatch(self, job: dict, worker: ComfyUIClient) -> str:
        params = job.get("params") or {}
        graph = build_graph_for_worker(self.jobs, worker, job["workflow"], params)
        return worker.queue_prompt(graph)

    def _start_polling(self, job_id: str, worker: ComfyUIClient) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        thread = threading.Thread(
            target=_run_polling,
            args=(self.jobs, worker, job),
            daemon=True,
            name=f"mpwe-poll-{job_id}",
        )
        self._poll_threads[job_id] = thread
        thread.start()
        self._prune_poll_threads()

    def _prune_poll_threads(self) -> None:
        self._poll_threads = {
            k: t for k, t in self._poll_threads.items() if t.is_alive()
        }

    def _mark_worker_down(self, worker: ComfyUIClient) -> None:
        self._worker_down_until[worker.base_url] = time.time() + self.worker_down_grace_s

    # ---------------- 对外查询 ----------------
    def client_for(self, url: str) -> ComfyUIClient | None:
        url = (url or "").rstrip("/")
        return next((w for w in self.workers if w.base_url == url), None)

    def stats(self) -> dict:
        s = self.jobs.stats()
        v = self.vram.stats(s["reserved_mb"])
        now = time.time()
        s.update(
            {
                "workers": [
                    {
                        "url": w.base_url,
                        "down": now < self._worker_down_until.get(w.base_url, 0.0),
                    }
                    for w in self.workers
                ],
                "total_mb": v["total_mb"],
                "headroom_mb": v["headroom_mb"],
                "capacity_mb": v["capacity_mb"],
                "free_mb": v["free_mb"],
            }
        )
        return s

    def poll_thread_join(self, job_id: str, timeout: float = 60) -> None:
        """测试辅助：等待某个任务的轮询线程结束。"""
        t = self._poll_threads.get(job_id)
        if t and t.is_alive():
            t.join(timeout=timeout)


__all__ = ["JobScheduler", "build_graph_for_worker"]
