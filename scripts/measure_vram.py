"""显存峰值测量脚本：为每个模型在多个分辨率档实测峰值，写入 data/vram_estimates.json。

用法（在项目根目录，ComfyUI 空闲时执行）：
    .venv\\Scripts\\python.exe scripts\\measure_vram.py
    .venv\\Scripts\\python.exe scripts\\measure_vram.py --models "ItNsComicMerge.safetensors" --tiers 512x512,512x768
    .venv\\Scripts\\python.exe scripts\\measure_vram.py --force   # 队列非空也继续

说明：
  - 逐模型逐档顺序跑（不并行），避免互相干扰；
  - 峰值采样优先 nvidia-smi（python 进程），缺失时退化为轮询 ComfyUI
    /system_stats 的 vram_free（total - 最小空闲）；
  - 结果合并进 data/vram_estimates.json，已有档位会被覆盖更新。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.comfyui import workflows  # noqa: E402
from app.comfyui.client import ComfyUIClient, ComfyUIError  # noqa: E402
from app.comfyui.presets import CHECKPOINT_PRESETS, DIFFUSION_PRESETS  # noqa: E402
from app.config import load_config  # noqa: E402

ESTIMATES_FILE = ROOT / "data" / "vram_estimates.json"
DEFAULT_TIERS = ["512x512", "512x768", "768x1024", "1024x1536"]
TEST_PROMPT = "a simple test card, clean background, sharp focus"


def _nvidia_smi_peak(pid_filter: str = "python") -> tuple[int, int]:
    """返回 (max_python_mb, min_free_mb)，采样失败返回 (0, 0)。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0, 0
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.used,memory.free,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().splitlines()
        if not out:
            return 0, 0
        used, free, total = (int(x) for x in out[0].split(","))
        return used, free
    except Exception:
        return 0, 0


class VramSampler:
    """后台采样线程：nvidia-smi 缺失时用 /system_stats 的空闲显存。"""

    def __init__(self, client: ComfyUIClient) -> None:
        self.client = client
        self.peak_used = 0
        self.min_free = None
        self.total = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _sample(self) -> None:
        while not self._stop.is_set():
            used, free = _nvidia_smi_peak()
            if used <= 0 and free <= 0:
                # 退化：轮询 ComfyUI 空闲显存
                try:
                    stats = self.client.get_system_stats()
                    dev = (stats.get("devices") or [{}])[0]
                    self.total = int(dev.get("vram_total") or 0) // (1024 * 1024)
                    free = int(dev.get("vram_free") or 0) // (1024 * 1024)
                except ComfyUIError:
                    free = 0
            if free > 0:
                self.min_free = free if self.min_free is None else min(self.min_free, free)
            self.peak_used = max(self.peak_used, used)
            self._stop.wait(0.2)

    def result_mb(self) -> int:
        """峰值 = max(nvidia 进程占用, 总显存 - 最小空闲)。"""
        if self.min_free is not None and self.total:
            return max(self.peak_used, self.total - self.min_free)
        return self.peak_used


def _run_one(client: ComfyUIClient, workflow: dict, timeout: int = 300) -> None:
    pid = client.queue_prompt(workflow)
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = client.get_history(pid)
        entry = history.get(pid)
        if entry:
            status = entry.get("status", {})
            if status.get("completed") or status.get("status_str") in ("success", "completed"):
                return
            if status.get("status_str") == "error":
                raise ComfyUIError(f"ComfyUI 执行出错: {status.get('messages', [])}")
        time.sleep(0.5)
    raise ComfyUIError(f"任务超时（{timeout}s）: {pid}")


def main() -> int:
    parser = argparse.ArgumentParser(description="实测模型峰值显存，更新 vram_estimates.json")
    parser.add_argument("--models", default="", help="逗号分隔的模型文件名；空 = 全部预设模型")
    parser.add_argument("--tiers", default="", help="逗号分隔的分辨率档，如 512x512,768x1024")
    parser.add_argument("--force", action="store_true", help="ComfyUI 队列非空也继续")
    parser.add_argument("--base-url", default="", help="ComfyUI 地址（默认取 config.yaml）")
    args = parser.parse_args()

    config = load_config()
    base_url = args.base_url or config["comfyui"]["base_url"]
    client = ComfyUIClient(base_url=base_url, timeout=60, client_id="mpwe-measure")

    try:
        queue = client.get_queue()
    except ComfyUIError as exc:
        print(f"[错误] 无法连接 ComfyUI（{base_url}）：{exc}")
        return 1
    if (queue.get("queue_running") or queue.get("queue_pending")) and not args.force:
        print("[错误] ComfyUI 队列非空，测量会受干扰。请稍后再跑，或加 --force 强制。")
        return 1

    presets: dict[str, dict] = {}
    presets.update(CHECKPOINT_PRESETS)
    presets.update(DIFFUSION_PRESETS)
    if args.models:
        wanted = {m.strip() for m in args.models.split(",") if m.strip()}
        presets = {k: v for k, v in presets.items() if k in wanted}
    if not presets:
        print("[错误] 没有可测量的模型（model_configs/ 下没有预设）")
        return 1
    tiers = [t.strip() for t in (args.tiers.split(",") if args.tiers else DEFAULT_TIERS) if t.strip()]

    estimates: dict = {}
    if ESTIMATES_FILE.exists():
        estimates = json.loads(ESTIMATES_FILE.read_text(encoding="utf-8"))
    models = estimates.setdefault("models", {})
    gpu = estimates.setdefault(
        "gpu",
        {"name": "NVIDIA GeForce RTX 4060 Laptop GPU", "total_vram_mb": 8188, "headroom_mb": 512},
    )

    for model_file, preset in presets.items():
        workflow_name = preset.get("workflow") or "txt2img"
        params = dict(preset.get("params") or {})
        base = dict(preset)
        base.update(params)
        print(f"\n=== {model_file}（workflow={workflow_name}）===")
        rec = models.setdefault(model_file, {"size_mb": 0, "measured_from": "", "resolutions": {}})
        if not rec.get("size_mb"):
            for sub in ("checkpoints", "diffusion_models"):
                p = Path(r"D:\Comfy-Desktop\ComfyUI-Shared\models") / sub / model_file
                if p.exists():
                    rec["size_mb"] = round(p.stat().st_size / 1024 / 1024, 1)
                    break
        res = rec.setdefault("resolutions", {})
        for tier in tiers:
            try:
                w, h = (int(x) for x in tier.lower().split("x"))
            except ValueError:
                print(f"  [跳过] 无效分辨率档: {tier}")
                continue
            kwargs: dict = {
                "prompt": TEST_PROMPT,
                "negative_prompt": "",
                "width": w,
                "height": h,
                "steps": int(base.get("steps", 20)),
                "cfg": float(base.get("cfg", 6.0)),
                "sampler": base.get("sampler", "euler"),
                "scheduler": base.get("scheduler", "normal"),
                "seed": 12345,
                "filename_prefix": "MPWE_VRAM_TEST",
                "hires_fix": False,
                "face_detailer": False,
                "loras": [],
            }
            if workflow_name in ("z_image_txt2img", "anima_txt2img"):
                kwargs["unet_name"] = model_file
            else:
                kwargs["checkpoint"] = model_file
            try:
                graph = workflows.build_workflow(workflow_name, **kwargs)
            except Exception as exc:
                print(f"  [跳过] {tier} 构建工作流失败: {exc}")
                continue
            sampler = VramSampler(client)
            sampler.start()
            t0 = time.time()
            try:
                _run_one(client, graph)
                peak = sampler.result_mb()
            except ComfyUIError as exc:
                print(f"  [失败] {tier}: {exc}")
                sampler.stop()
                continue
            finally:
                sampler.stop()
            res[tier] = peak
            rec["measured_from"] = f"实测 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            print(f"  {tier}: 峰值 {peak} MB（耗时 {time.time() - t0:.1f}s）")
            ESTIMATES_FILE.write_text(
                json.dumps(estimates, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    print(f"\n完成。结果已写入 {ESTIMATES_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
