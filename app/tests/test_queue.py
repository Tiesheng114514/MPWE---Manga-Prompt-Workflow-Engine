"""排队调度器 + 显存预算 单元测试（离线，使用 mock ComfyUI 实例与临时数据库）。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import app.core.jobs as jobs_mod  # noqa: E402
from app.comfyui.client import ComfyUIError  # noqa: E402
from app.core import billing  # noqa: E402
from app.core.jobs import JobManager  # noqa: E402
from app.core.queue import JobScheduler  # noqa: E402
from app.core.vram import VramBudget  # noqa: E402


class FakeComfyUI:
    """最小可用的 mock ComfyUI 实例。"""

    def __init__(self, base_url: str, fail_submit: bool = False, delay: float = 0.0) -> None:
        self.base_url = base_url
        self.fail_submit = fail_submit
        self.delay = delay
        self.prompt_count = 0
        self._ready_at: dict[str, float] = {}

    def queue_prompt(self, workflow: dict, extra_data: dict | None = None) -> str:
        if self.fail_submit:
            raise ComfyUIError("mock 提交失败（模拟实例故障）")
        self.prompt_count += 1
        pid = f"pid-{self.base_url}-{self.prompt_count}"
        self._ready_at[pid] = time.time() + self.delay
        return pid

    def get_history(self, prompt_id: str | None = None) -> dict:
        pid = prompt_id or f"pid-{self.base_url}-{self.prompt_count}"
        if time.time() < self._ready_at.get(pid, 0):
            return {}
        return {
            pid: {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": f"{pid}.png", "subfolder": "", "type": "output"}]}},
            }
        }

    def get_prompt_output_images(self, prompt_id: str) -> list[dict]:
        return [{"filename": f"{prompt_id}.png", "subfolder": "", "type": "output"}]

    def get_image(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        return b"fake-png-bytes"

    def cancel_prompt(self, prompt_id: str) -> None:
        pass

    def interrupt(self) -> None:
        pass


class _Env:
    """每个测试独立的临时 DB + 输出目录。"""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mpwe_queue_test_"))
        os.environ["MPWE_DB_PATH"] = str(self.tmp / "mpwe_test.db")
        billing._db = None  # 重置计费库缓存，指向临时库
        self.out_dir = self.tmp / "out"
        jobs_mod._user_image_dir = lambda config, uid, job_id: self._job_out(uid, job_id)
        self.config = {
            "queue": {
                "max_concurrent_per_user": 2,
                "poll_interval_s": 0.05,
                "worker_down_grace_s": 0.5,
                "max_dispatch_attempts": 3,
            },
            "billing": {"image": {"price_per_image": 0.3}},
        }

    def _job_out(self, uid: str, job_id: str) -> Path:
        p = self.out_dir / uid / job_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def make(self, workers: list[FakeComfyUI], vram: VramBudget | None = None) -> JobScheduler:
        jobs = JobManager(self.config)
        return JobScheduler(self.config, jobs, workers, vram or VramBudget(self.config))


def _wait_for(jobs: JobManager, job_id: str, statuses: set[str], timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get(job_id)
        if job and job["status"] in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"等待 {job_id} 状态 {statuses} 超时，当前: {jobs.get(job_id)}")


def _sd15_params(**overrides) -> dict:
    params = {
        "checkpoint": "ItNsComicMerge.safetensors",
        "prompt": "test",
        "negative_prompt": "",
        "width": 512,
        "height": 768,
        "steps": 5,
        "cfg": 6.0,
        "sampler": "euler",
        "scheduler": "normal",
        "seed": 1,
        "batch_size": 1,
    }
    params.update(overrides)
    return params


# ---------------- 显存预算 ----------------

def test_vram_budget_exact_and_interpolation() -> None:
    b = VramBudget({})
    # 精确档
    assert b.model_peak_mb("ItNsComicMerge.safetensors", 512, 512) == 3048
    # 无精确档：按潜空间面积线性插值（768x1152 应落在 768x1024=5026 与 1024x1536=7138 之间）
    peak = b.model_peak_mb("ItNsComicMerge.safetensors", 768, 1152)
    assert 5026 < peak < 7138, peak
    # 大模型（SDXL）低分辨率也接近 7G
    big = b.model_peak_mb("one obsession_v14.safetensors", 1024, 1024)
    assert big > 7000
    # 超分/脸部只会更高
    assert b.model_peak_mb("ItNsComicMerge.safetensors", 512, 512, hires=True) >= 3048
    assert b.model_peak_mb("ItNsComicMerge.safetensors", 512, 512, face_detailer=True) == 3048 + 300
    # 未测模型：保守兜底，且不超总显存
    unknown = b.model_peak_mb("brand-new-model.safetensors", 512, 512)
    assert 0 < unknown <= b.total_mb


def test_vram_budget_fits() -> None:
    b = VramBudget({})
    cap = b.capacity_mb()
    # 2 路 SD1.5 小分辨率放得下
    assert b.fits(0, 3200)
    assert b.fits(3200, 3200)
    # 大模型占满后，小任务也进不去
    assert not b.fits(7000, 3200)
    assert cap == b.total_mb - b.headroom_mb


# ---------------- 调度器 ----------------

def test_two_small_jobs_run_in_parallel() -> None:
    env = _Env()
    w1, w2 = FakeComfyUI("http://127.0.0.1:8188", delay=0.2), FakeComfyUI("http://127.0.0.1:8189", delay=0.2)
    sched = env.make([w1, w2])
    sched.start()
    try:
        j1 = sched.jobs.enqueue("txt2img", _sd15_params(), "u1", reserved_mb=3200)
        j2 = sched.jobs.enqueue("txt2img", _sd15_params(), "u2", reserved_mb=3200)
        sched.wake()
        # 两个任务应分到两个实例同时跑
        deadline = time.time() + 5
        while time.time() < deadline and sched.jobs.stats()["running"] < 2:
            time.sleep(0.05)
        stats = sched.jobs.stats()
        assert stats["running"] == 2, stats
        done1 = _wait_for(sched.jobs, j1["id"], {"done"})
        done2 = _wait_for(sched.jobs, j2["id"], {"done"})
        assert done1["status"] == "done" and done2["status"] == "done"
        assert w1.prompt_count == 1 and w2.prompt_count == 1, (w1.prompt_count, w2.prompt_count)
    finally:
        sched.stop()


def test_big_job_blocks_small_until_slot_free() -> None:
    env = _Env()
    w1 = FakeComfyUI("http://127.0.0.1:8188", delay=0.5)
    w2 = FakeComfyUI("http://127.0.0.1:8189", delay=0.05)
    sched = env.make([w1, w2])
    sched.start()
    try:
        big = sched.jobs.enqueue("txt2img", _sd15_params(width=1024, height=1536), "u1", reserved_mb=7000)
        small = sched.jobs.enqueue("txt2img", _sd15_params(), "u2", reserved_mb=3200)
        sched.wake()
        # 7000 + 3200 > 预算 → 小任务必须等大任务跑完
        _wait_for(sched.jobs, big["id"], {"running"})
        time.sleep(0.15)  # 大任务仍在运行期间
        assert sched.jobs.get(small["id"])["status"] == "queued", "大任务占用预算时小任务不应放行"
        _wait_for(sched.jobs, big["id"], {"done"})
        _wait_for(sched.jobs, small["id"], {"done"})
        assert w1.prompt_count == 1 and w2.prompt_count == 1
    finally:
        sched.stop()


def test_per_user_concurrency_limit() -> None:
    env = _Env()
    env.config["queue"]["max_concurrent_per_user"] = 1
    w1, w2 = FakeComfyUI("http://127.0.0.1:8188", delay=0.3), FakeComfyUI("http://127.0.0.1:8189", delay=0.05)
    sched = env.make([w1, w2])
    sched.start()
    try:
        j1 = sched.jobs.enqueue("txt2img", _sd15_params(), "u1", reserved_mb=3200)
        j2 = sched.jobs.enqueue("txt2img", _sd15_params(), "u1", reserved_mb=3200)
        sched.wake()
        _wait_for(sched.jobs, j1["id"], {"running", "done"})
        # 同一用户第二个任务必须排队
        time.sleep(0.15)
        assert sched.jobs.get(j2["id"])["status"] == "queued"
        _wait_for(sched.jobs, j2["id"], {"done"}, timeout=8)
    finally:
        sched.stop()


def test_worker_down_retry_on_other_instance() -> None:
    env = _Env()
    w_bad = FakeComfyUI("http://127.0.0.1:8188", fail_submit=True)
    w_ok = FakeComfyUI("http://127.0.0.1:8189", delay=0.05)
    sched = env.make([w_bad, w_ok])
    sched.start()
    try:
        job = sched.jobs.enqueue("txt2img", _sd15_params(), "u1", reserved_mb=3200)
        sched.wake()
        done = _wait_for(sched.jobs, job["id"], {"done"})
        assert done["status"] == "done"
        assert w_bad.prompt_count == 0
        assert w_ok.prompt_count == 1
    finally:
        sched.stop()


def test_queue_position_and_cancel() -> None:
    env = _Env()
    w1 = FakeComfyUI("http://127.0.0.1:8188", delay=0.5)
    sched = env.make([w1])
    sched.start()
    try:
        j1 = sched.jobs.enqueue("txt2img", _sd15_params(), "u1", reserved_mb=3200)
        j2 = sched.jobs.enqueue("txt2img", _sd15_params(), "u2", reserved_mb=7000)
        assert sched.jobs.get(j1["id"])["queue_pos"] == 1
        assert sched.jobs.get(j2["id"])["queue_pos"] == 2
        # 取消前面排队的小任务 → 后面的位置前移
        sched.jobs.cancel(j1["id"])
        assert sched.jobs.get(j2["id"])["queue_pos"] == 1
        # 取消运行中的任务（worker_url 已在 claim 后写入）
        j3 = sched.jobs.enqueue("txt2img", _sd15_params(), "u3", reserved_mb=3200)
        _wait_for(sched.jobs, j3["id"], {"running"})
        sched.jobs.cancel(j3["id"])
        assert sched.jobs.get(j3["id"])["status"] == "canceled"
    finally:
        sched.stop()


def test_restart_recover_marks_running_as_error() -> None:
    env = _Env()
    jobs = JobManager(env.config)
    job = jobs.enqueue("txt2img", _sd15_params(), "u1", reserved_mb=3200)
    jobs.update(job["id"], status="running", worker_url="http://127.0.0.1:8188", prompt_id="stray")
    assert jobs.restart_recover() == 1
    recovered = jobs.get(job["id"])
    assert recovered["status"] == "error"
    assert "重启" in (recovered["error"] or "")


if __name__ == "__main__":
    test_vram_budget_exact_and_interpolation()
    test_vram_budget_fits()
    test_two_small_jobs_run_in_parallel()
    test_big_job_blocks_small_until_slot_free()
    test_per_user_concurrency_limit()
    test_worker_down_retry_on_other_instance()
    test_queue_position_and_cancel()
    test_restart_recover_marks_running_as_error()
    print("ALL OK")
