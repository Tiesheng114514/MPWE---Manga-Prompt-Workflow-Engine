"""显存预算与峰值估算（多用户并行准入的依据）。

核心规则（来自老项目实测 + 社区共识）：
  - 同时运行的任务峰值显存之和 <= 总显存 - 余量，才允许并行；
  - 每个 ComfyUI 实例同时只跑 1 个任务（单进程单卡的硬限制），
    并行 = 多个实例，准入控制器跨实例做预算；
  - SD1.5 等小模型在低分辨率下峰值只有 ~3GB，8G 卡可开 2 路；
    SDXL / Z-Image（含 Qwen 文本编码器）峰值 7GB+，永远只能 1 路。

峰值优先取实测表（data/vram_estimates.json，按 模型 x 分辨率），
没有精确档按潜空间面积在最近两档间线性插值/外推；
完全没测过的模型按 文件大小 x 精度系数 + 固定上下文 + 激活增量 保守估算
（宁可高估，绝不低估，避免 OOM）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.db import PROJECT_ROOT

DEFAULT_ESTIMATES_FILE = PROJECT_ROOT / "data" / "vram_estimates.json"

# 已知模型目录（用于兜底估算时读模型文件大小；ComfyUI 的 extra_model_paths 指向这里）
DEFAULT_MODEL_DIRS = [
    Path(r"D:\Comfy-Desktop\ComfyUI-Shared\models"),
]

_BASELINE_CTX_MB = 1800.0          # ComfyUI 进程 + CUDA 上下文固定占用
_ACTIVATION_PER_512SQ_MB = 900.0   # 512x512 基准的采样激活增量
_FACE_DETAILER_EXTRA_MB = 300      # FaceDetailer 小区域重绘附加占用


def _load_estimates(path: Path | None = None) -> dict:
    path = Path(path or DEFAULT_ESTIMATES_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _latent_area(width: int, height: int) -> float:
    return max(1.0, float((max(1, int(width)) // 8) * (max(1, int(height)) // 8)))


class VramBudget:
    """显存预算：总显存 / 余量 / 容量 + 每个任务的峰值估算。"""

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        queue_cfg = cfg.get("queue") or {}
        vram_cfg = cfg.get("vram") or {}
        est_path = vram_cfg.get("estimates_file") or queue_cfg.get("estimates_file")
        self.estimates = _load_estimates(Path(est_path) if est_path else None)
        gpu = self.estimates.get("gpu") or {}
        self.total_mb = int(
            vram_cfg.get("total_vram_mb")
            or queue_cfg.get("total_vram_mb")
            or gpu.get("total_vram_mb")
            or 8188
        )
        self.headroom_mb = int(
            vram_cfg.get("headroom_mb")
            or queue_cfg.get("headroom_mb")
            or gpu.get("headroom_mb")
            or 512
        )
        model_dirs = vram_cfg.get("model_dirs") or queue_cfg.get("model_dirs")
        self.model_dirs = [Path(d) for d in (model_dirs or DEFAULT_MODEL_DIRS)]
        self._fallback_cache: dict[str, int] = {}

    # ---------------- 容量 ----------------
    def capacity_mb(self) -> int:
        """可用预算 = 总显存 - 余量。"""
        return max(1, self.total_mb - self.headroom_mb)

    def fits(self, reserved_mb: int, cost_mb: int) -> bool:
        return reserved_mb + cost_mb <= self.capacity_mb()

    # ---------------- 峰值估算 ----------------
    def model_peak_mb(
        self,
        model_file: str,
        width: int = 1024,
        height: int = 1024,
        hires: bool = False,
        face_detailer: bool = False,
    ) -> int:
        """某模型在指定尺寸（可带超分/脸部修复）下的峰值显存估算（MB）。"""
        model_file = (model_file or "").strip()
        rec = self.estimates.get("models", {}).get(model_file) or {}
        main_peak = self._peak_at(rec, model_file, width, height)
        if hires:
            hires_peak = self._peak_at(rec, model_file, width * 2, height * 2)
            main_peak = max(main_peak, hires_peak)
        if face_detailer:
            main_peak += _FACE_DETAILER_EXTRA_MB
        return int(min(max(main_peak, 1), self.total_mb))

    def job_peak_mb(self, params: dict[str, Any] | None, workflow: str = "txt2img") -> int:
        """按生成参数估算整个任务（含超分/脸部修复）的峰值显存。"""
        params = params or {}
        model = params.get("checkpoint") or params.get("unet_name") or ""
        width = max(64, int(params.get("width") or 1024))
        height = max(64, int(params.get("height") or 1024))
        hires = bool(params.get("hires_fix"))
        face = bool(params.get("face_detailer"))
        peak = self.model_peak_mb(model, width, height, hires=hires, face_detailer=face)
        # 多张同跑时按张数近似线性（保守，batch 会同时驻留多份中间张量）
        batch = max(1, int(params.get("batch_size") or 1))
        if batch > 1:
            peak = int(min(self.total_mb, peak + (batch - 1) * (peak - _BASELINE_CTX_MB) * 0.5))
        return peak

    def _peak_at(self, rec: dict, model_file: str, width: int, height: int) -> int:
        tiers = rec.get("resolutions") or {}
        if tiers:
            area = _latent_area(width, height)
            points = sorted(
                ((int(k.split("x")[0]) // 8) * (int(k.split("x")[1]) // 8), int(v))
                for k, v in tiers.items()
                if isinstance(v, (int, float)) and v > 0
            )
            if points:
                exact = next((v for a, v in points if abs(a - area) < 1e-9), None)
                if exact is not None:
                    return exact
                return int(_interpolate(points, area))
        return self._fallback_peak(model_file, width, height)

    def _fallback_peak(self, model_file: str, width: int, height: int) -> int:
        """没有实测数据时的保守估算：文件大小 x 精度 + 上下文 + 激活。"""
        if model_file in self._fallback_cache:
            return self._fallback_cache[model_file]
        size_mb = self._model_file_size_mb(model_file)
        low = (model_file or "").lower()
        precision = 0.55 if ("fp8" in low or "int8" in low) else 1.0
        base = _BASELINE_CTX_MB + size_mb * precision
        act = _ACTIVATION_PER_512SQ_MB * (_latent_area(width, height) / 262144.0)
        peak = int(base + act)
        self._fallback_cache[model_file] = peak
        return peak

    def _model_file_size_mb(self, model_file: str) -> float:
        for root in self.model_dirs:
            for sub in ("checkpoints", "diffusion_models"):
                p = root / sub / model_file
                if p.exists():
                    return p.stat().st_size / 1024 / 1024
        return float(2048.0)

    def stats(self, reserved_mb: int = 0) -> dict:
        return {
            "total_mb": self.total_mb,
            "headroom_mb": self.headroom_mb,
            "capacity_mb": self.capacity_mb(),
            "reserved_mb": int(reserved_mb),
            "free_mb": max(0, self.capacity_mb() - int(reserved_mb)),
        }


def _interpolate(points: list[tuple[float, int]], area: float) -> float:
    """按潜空间面积线性插值/外推峰值。points 已按面积升序。"""
    if area <= points[0][0]:
        x0, y0 = points[0]
        x1, y1 = points[1] if len(points) > 1 else (x0 * 2, y0)
    elif area >= points[-1][0]:
        x0, y0 = points[-2] if len(points) > 1 else points[0]
        x1, y1 = points[-1]
    else:
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= area <= x1:
                break
    if x1 == x0:
        return float(y0)
    return y0 + (y1 - y0) * (area - x0) / (x1 - x0)


def load_vram_budget(config: dict | None = None) -> VramBudget:
    return VramBudget(config)


__all__ = ["VramBudget", "load_vram_budget"]
