"""任务管理：SQLite 持久化的作业登记 + 后台轮询 ComfyUI 执行结果与进度。

每个任务归属一个用户（user_id），图片下载到 data/users/<uid>/<job_id>/ 落盘；
任务完成时记录 GPU 耗时与估算算力，并按张数扣图片钱包。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import websocket

from app.core import billing, gpu_metrics
from app.core.db import PROJECT_ROOT, init_mpwe_db
from app.core.runlog import append_run
from app.comfyui.client import ComfyUIClient, ComfyUIError

_JOB_TIMEOUT = 900  # 重活（大图超分+脸部修复）可能超过 5 分钟，放宽到 15 分钟

# 各采样阶段的进度窗口：主生成占前半（0-50%），画质增强（超分/脸部）占后半（50-100%）。
_MAIN_NODES = {"txt2img": "3", "z_image_txt2img": "7", "anima_txt2img": "7"}
_HIRES_NODE = "23"
_FACE_NODE = "31"

def _image_dict(row) -> dict:
    return {
        "filename": row["filename"],
        "subfolder": row["subfolder"] or "",
        "type": row["image_type"] or "output",
        "local_path": row["local_path"],
        "seq": int(row["seq"]),
        "width": row["width"],
        "height": row["height"],
    }


def _load_images(db: Database, job_id: str) -> list[dict]:
    with db.conn() as conn:
        rows = conn.execute(
            "SELECT * FROM job_images WHERE job_id = ? ORDER BY seq", (job_id,)
        ).fetchall()
    return [_image_dict(r) for r in rows]


def _job_dict(db: Database, row) -> dict:
    job = dict(row)
    job["params"] = json.loads(job.get("params") or "{}")
    job["queue_pos"] = None
    job["images"] = _load_images(db, job["id"])
    if job.get("status") == "queued":
        job["queue_pos"] = _queue_position(db, job["id"])
    return job


def _queue_position(db: Database, job_id: str) -> int | None:
    """当前排队中的位置（1 起）；不在队列返回 None。"""
    with db.conn() as conn:
        row = conn.execute(
            "SELECT priority, created_at FROM jobs WHERE id = ? AND status = 'queued'",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        pos = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND "
            "(priority > ? OR (priority = ? AND created_at < ?))",
            (row["priority"], row["priority"], row["created_at"]),
        ).fetchone()[0]
    return int(pos) + 1


class JobManager:
    """生成任务的登记与状态管理（SQLite 持久化，重启不丢）。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.db = init_mpwe_db()
        self._lock = threading.Lock()

    def enqueue(
        self,
        workflow: str,
        params: dict,
        user_id: str,
        priority: int = 0,
        reserved_mb: int | None = None,
    ) -> dict:
        """登记一个排队任务（不提交 ComfyUI，由调度器按预算领取）。"""
        job = {
            "id": uuid.uuid4().hex[:12],
            "user_id": user_id,
            "prompt_id": None,
            "workflow": workflow,
            "params": params,
            "status": "queued",
            "progress": 0,
            "stage": "排队中",
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "gpu_seconds": None,
            "gpu_flops_estimate": None,
            "priority": int(priority or 0),
            "worker_url": None,
            "reserved_mb": int(reserved_mb or 0),
            "attempts": 0,
        }
        with self._lock:
            with self.db.conn() as conn:
                conn.execute(
                    "INSERT INTO jobs (id, user_id, prompt_id, workflow, params, status, progress, stage, "
                    "error, created_at, updated_at, started_at, finished_at, gpu_seconds, gpu_flops_estimate, "
                    "priority, worker_url, reserved_mb, attempts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job["id"],
                        user_id,
                        None,
                        workflow,
                        json.dumps(params, ensure_ascii=False),
                        job["status"],
                        0,
                        "排队中",
                        None,
                        job["created_at"],
                        job["updated_at"],
                        None,
                        None,
                        None,
                        None,
                        job["priority"],
                        None,
                        job["reserved_mb"],
                        0,
                    ),
                )
        return self.get(job["id"])  # type: ignore[return-value]

    def claim(self, job_id: str, worker_url: str, prompt_id: str, reserved_mb: int) -> None:
        """调度器领取任务：提交到 ComfyUI 后标记运行中。"""
        with self._lock:
            with self.db.conn() as conn:
                conn.execute(
                    "UPDATE jobs SET status = 'running', progress = 1, stage = '生成中…', "
                    "started_at = ?, worker_url = ?, prompt_id = ?, reserved_mb = ?, attempts = attempts + 1, "
                    "updated_at = ? WHERE id = ?",
                    (time.time(), worker_url, prompt_id, int(reserved_mb), time.time(), job_id),
                )

    def fail(self, job_id: str, error: str) -> None:
        self.update(job_id, status="error", error=str(error)[:500], stage="失败")

    def bump_attempts(self, job_id: str) -> int:
        """提交失败计数 +1，返回当前总次数（仅排队任务）。"""
        with self._lock:
            with self.db.conn() as conn:
                conn.execute(
                    "UPDATE jobs SET attempts = attempts + 1, updated_at = ? WHERE id = ? AND status = 'queued'",
                    (time.time(), job_id),
                )
                row = conn.execute(
                    "SELECT attempts FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
        return int(row["attempts"]) if row else 0

    def list_queued(self, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE status = 'queued' ORDER BY priority DESC, created_at ASC LIMIT ?"
        with self.db.conn() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [_job_dict(self.db, r) for r in rows]

    def list_running(self) -> list[dict]:
        with self.db.conn() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE status = 'running'").fetchall()
        return [_job_dict(self.db, r) for r in rows]

    def stats(self) -> dict:
        with self.db.conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall()
            reserved = conn.execute(
                "SELECT COALESCE(SUM(reserved_mb), 0) AS s FROM jobs WHERE status = 'running'"
            ).fetchone()["s"]
        counts = {r["status"]: int(r["c"]) for r in rows}
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "error": counts.get("error", 0),
            "canceled": counts.get("canceled", 0),
            "reserved_mb": int(reserved or 0),
        }

    def restart_recover(self) -> int:
        """服务重启恢复：把残留 running 任务标为失败（轮询线程已随进程消失）。"""
        with self._lock:
            with self.db.conn() as conn:
                rows = conn.execute(
                    "SELECT id FROM jobs WHERE status = 'running'"
                ).fetchall()
                for r in rows:
                    conn.execute(
                        "UPDATE jobs SET status = 'error', error = '服务重启，任务中断未完成', "
                        "stage = '失败', updated_at = ? WHERE id = ?",
                        (time.time(), r["id"]),
                    )
        return len(rows)

    def update(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "status", "progress", "stage", "error", "prompt_id", "started_at",
            "finished_at", "gpu_seconds", "gpu_flops_estimate",
        }
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sets = ", ".join(f"{c} = ?" for c in cols)
        values = [fields[c] for c in cols]
        with self._lock:
            with self.db.conn() as conn:
                conn.execute(
                    f"UPDATE jobs SET {sets}, updated_at = ? WHERE id = ?",
                    (*values, time.time(), job_id),
                )

    def get(self, job_id: str) -> dict | None:
        with self.db.conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return _job_dict(self.db, row)

    def list(self, limit: int = 50, user_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM jobs"
        args: list[Any] = []
        if user_id:
            sql += " WHERE user_id = ?"
            args.append(user_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.db.conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_job_dict(self.db, r) for r in rows]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            with self.db.conn() as conn:
                row = conn.execute(
                    "SELECT status FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if row and row["status"] in ("queued", "running"):
                    conn.execute(
                        "UPDATE jobs SET status = 'canceled', stage = '已取消', progress = 0, "
                        "updated_at = ? WHERE id = ?",
                        (time.time(), job_id),
                    )
                    return True
        return False

    def prune(self, keep: int = 500) -> None:
        """数据库里只保留最近的 keep 个任务，防止无限膨胀。"""
        with self._lock:
            with self.db.conn() as conn:
                rows = conn.execute(
                    "SELECT id FROM jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?", (keep,)
                ).fetchall()
                for r in rows:
                    conn.execute("DELETE FROM job_images WHERE job_id = ?", (r["id"],))
                    conn.execute("DELETE FROM jobs WHERE id = ?", (r["id"],))


def _ws_url(client: ComfyUIClient) -> str:
    base = client.base_url.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/ws?clientId={client.client_id}"


def _stage_windows(job: dict) -> list[dict]:
    """根据工作流与开关，计算各采样阶段的 (node, 阶段名, 起点%, 终点%)。"""
    params = job.get("params") or {}
    workflow = job.get("workflow") or "txt2img"
    hires = bool(params.get("hires_fix"))
    face = bool(params.get("face_detailer"))
    stages: list[dict] = []

    if workflow == "quality_pass":
        if hires:
            stages.append({"nodes": {_HIRES_NODE}, "label": "超分重绘中", "start": 0.0, "end": 50.0 if face else 100.0})
        if face:
            stages.append({"nodes": {_FACE_NODE}, "label": "脸部修复中", "start": 50.0 if hires else 0.0, "end": 100.0})
        if not stages:
            stages.append({"nodes": {_HIRES_NODE, _FACE_NODE}, "label": "生成中", "start": 0.0, "end": 100.0})
        return stages

    main_node = _MAIN_NODES.get(workflow, "3")
    stages.append(
        {
            "nodes": {main_node},
            "label": "生成主图中",
            "start": 0.0,
            "end": 50.0 if (hires or face) else 100.0,
        }
    )
    if hires and face:
        stages.append({"nodes": {_HIRES_NODE}, "label": "超分重绘中", "start": 50.0, "end": 75.0})
        stages.append({"nodes": {_FACE_NODE}, "label": "脸部修复中", "start": 75.0, "end": 100.0})
    elif hires:
        stages.append({"nodes": {_HIRES_NODE}, "label": "超分重绘中", "start": 50.0, "end": 100.0})
    elif face:
        stages.append({"nodes": {_FACE_NODE}, "label": "脸部修复中", "start": 50.0, "end": 100.0})
    return stages


def _node_of_entry(entry: dict) -> str | None:
    for key in ("display_node_id", "node_id", "real_node_id"):
        val = entry.get(key)
        if val is not None:
            return str(val)
    return None


def _overall_from_state(stages: list[dict], nodes: dict) -> tuple[float, str]:
    total = 0.0
    label = ""
    for st in stages:
        matched = None
        for nid, entry in nodes.items():
            if _node_of_entry(entry) in st["nodes"] or str(nid) in st["nodes"]:
                matched = entry
                break
        if matched is None:
            continue
        state = matched.get("state")
        label = st["label"]
        if state == "finished":
            total += st["end"] - st["start"]
        elif state == "running":
            try:
                maxv = float(matched.get("max") or 1)
                value = float(matched.get("value") or 0)
                frac = 0.0 if maxv <= 0 else min(1.0, max(0.0, value / maxv))
            except (TypeError, ValueError):
                frac = 0.0
            total += (st["end"] - st["start"]) * frac
    return total, label


def _overall_from_progress(stages: list[dict], node: str | None, value: float, maxv: float) -> tuple[float, str]:
    if not node:
        return 0.0, ""
    for st in stages:
        if node in st["nodes"]:
            frac = 0.0 if maxv <= 0 else min(1.0, max(0.0, value / maxv))
            return st["start"] + (st["end"] - st["start"]) * frac, st["label"]
    return 0.0, ""


def _user_image_dir(config: dict, uid: str, job_id: str) -> Path:
    root = PROJECT_ROOT / "data" / "users" / uid / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _finalize_job(job_manager: JobManager, client: ComfyUIClient, job: dict) -> None:
    """任务完成：记录 GPU 指标、图片落盘、按张数扣图片钱包。"""
    job_id = job["id"]
    uid = job["user_id"]
    params = job.get("params") or {}
    try:
        images = client.get_prompt_output_images(job["prompt_id"])
    except ComfyUIError as exc:
        job_manager.update(job_id, status="error", error=f"获取输出图片失败: {exc}")
        return

    local_images: list[dict] = []
    out_dir = _user_image_dir(job_manager.config, uid, job_id)
    for seq, img in enumerate(images or []):
        try:
            data = client.get_image(
                filename=img.get("filename", ""),
                subfolder=img.get("subfolder", ""),
                image_type=img.get("type", "output"),
            )
        except ComfyUIError:
            data = b""
        local_path = None
        if data:
            local_path = str(out_dir / f"{seq:03d}.png")
            Path(local_path).write_bytes(data)
        local_images.append(
            {
                "job_id": job_id,
                "seq": seq,
                "filename": img.get("filename", ""),
                "subfolder": img.get("subfolder", ""),
                "image_type": img.get("type", "output"),
                "local_path": local_path,
                "width": img.get("width"),
                "height": img.get("height"),
                "created_at": time.time(),
            }
        )

    with job_manager.db.conn() as conn:
        for row in local_images:
            conn.execute(
                "INSERT OR REPLACE INTO job_images (job_id, seq, filename, subfolder, image_type, "
                "local_path, width, height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["job_id"], row["seq"], row["filename"], row["subfolder"],
                    row["image_type"], row["local_path"], row["width"], row["height"],
                    row["created_at"],
                ),
            )

    finished_at = time.time()
    started_at = job.get("started_at") or job["created_at"]
    gpu_seconds = max(0.0, finished_at - started_at)
    flops = gpu_metrics.estimate_flops(params)
    job_manager.update(
        job_id,
        status="done",
        progress=100,
        stage="完成",
        finished_at=finished_at,
        gpu_seconds=round(gpu_seconds, 2),
        gpu_flops_estimate=flops,
    )

    # 按张数扣图片钱包（0.3 元/张，config 可调）
    price = (job_manager.config.get("billing") or {}).get("image", {}).get("price_per_image", 0.3)
    billing.charge_images(billing.billing_db(), uid, len(local_images), float(price), ref_id=job_id)

    model = (params.get("checkpoint") or params.get("unet_name") or "").strip()
    append_run(
        {
            "kind": "job_done",
            "user_id": uid,
            "job_id": job_id,
            "workflow": job.get("workflow"),
            "model": model,
            "status": "done",
            "image_count": len(local_images),
            "gpu_seconds": round(gpu_seconds, 2),
            "gpu_flops": flops,
            "tflops_hour": round(flops / 1e12 / 3600, 6),
            "created_at": job.get("created_at"),
        }
    )


def _run_polling(job_manager: JobManager, client: ComfyUIClient, job: dict) -> None:
    """后台线程：通过 ComfyUI websocket 收取进度事件，轮询 history 直到完成。"""
    job_id = job["id"]
    prompt_id = job["prompt_id"]
    stages = _stage_windows(job)
    ws = None
    try:
        job_manager.update(job_id, status="running", progress=1, stage=stages[0]["label"] if stages else "生成中…", started_at=time.time())
        try:
            ws = websocket.create_connection(_ws_url(client), timeout=5)
            ws.settimeout(0.2)
        except Exception:
            ws = None
        deadline = time.time() + _JOB_TIMEOUT
        last_pct = 0
        last_stage = ""
        while time.time() < deadline:
            snapshot = job_manager.get(job_id)
            if snapshot and snapshot.get("status") == "canceled":
                return
            if ws is not None:
                try:
                    msg = ws.recv()
                    if isinstance(msg, (bytes, bytearray)):
                        continue
                    data = json.loads(msg)
                    mtype = data.get("type")
                    if mtype == "progress":
                        d = data.get("data") or {}
                        node = d.get("node")
                        maxv = d.get("max") or 0
                        value = d.get("value") or 0
                        if maxv > 0:
                            overall, stage = _overall_from_progress(stages, str(node) if node is not None else None, value, maxv)
                            if overall <= 0 and stages:
                                overall = stages[0]["start"]
                                stage = stages[0]["label"]
                            pct = max(1, min(99, int(overall)))
                            if pct != last_pct or stage != last_stage:
                                last_pct = pct
                                last_stage = stage
                                job_manager.update(job_id, progress=pct, stage=stage)
                    elif mtype == "progress_state":
                        d = data.get("data") or {}
                        nodes = d.get("nodes") or {}
                        overall, stage = _overall_from_state(stages, nodes)
                        if not stage and stages:
                            stage = stages[0]["label"]
                        pct = max(1, min(99, int(overall)))
                        if pct != last_pct or stage != last_stage:
                            last_pct = pct
                            last_stage = stage
                            job_manager.update(job_id, progress=pct, stage=stage or last_stage)
                except websocket.WebSocketTimeoutException:
                    pass
                except (ValueError, KeyError, TypeError):
                    continue
                except Exception:
                    ws = None
            history = client.get_history(prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("completed") or status.get("status_str") == "completed":
                    _finalize_job(job_manager, client, job)
                    return
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI 执行出错: {status.get('messages', [])}")
            time.sleep(0.5)
        raise ComfyUIError(f"等待 ComfyUI 任务超时（{_JOB_TIMEOUT}s）: {prompt_id}")
    except ComfyUIError as exc:
        job_manager.update(job_id, status="error", error=str(exc))
        append_run(
            {
                "kind": "job_done",
                "user_id": job.get("user_id"),
                "job_id": job_id,
                "workflow": job.get("workflow"),
                "status": "error",
                "error": str(exc),
                "created_at": job.get("created_at"),
            }
        )
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


__all__ = ["JobManager"]
