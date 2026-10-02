"""FLUX.1 系列文生图（GGUF 量化 UNET + DualCLIP + FluxGuidance）。

结构：
    UnetLoaderGGUF(GGUF 量化 UNET) ─ [LoRA 链] ─ KSampler
    DualCLIPLoader(clip_l + t5xxl, type=flux) ─ CLIPTextEncode x2 ─ FluxGuidance ─ KSampler
    VAELoader(ae) ─ VAEDecode ─ [画质增强] ─ SaveImage

依赖 ComfyUI-GGUF 自定义节点（提供 UnetLoaderGGUF）。
FLUX 官方工作流的要点：CFG=1.0（引导由 FluxGuidance 控制，默认 3.5）、
euler + simple、20-28 步、没有负面提示词（CFG=1 时负面词基本无效）。
"""

from __future__ import annotations

import logging
import random
from typing import Any

from app.comfyui.presets import get_diffusion_preset

from .loras import attach_loras
from .quality import attach_quality_stage
from .registry import register

logger = logging.getLogger(__name__)


def _flux_only_loras(loras: list | None) -> list:
    """FLUX 只能叠加 FLUX 版 LoRA，混用 SDXL LoRA 会直接报形状错误。

    这里只保留文件名里带 flux 的 LoRA（大小写不敏感），其余丢弃并记日志。
    """
    if not loras:
        return []
    kept, dropped = [], []
    for item in loras:
        name = (item.file if hasattr(item, "file") else (item or {}).get("file", "")) or ""
        (kept if "flux" in name.lower() else dropped).append(item)
    if dropped:
        logger.warning(
            "已忽略 %d 个非 FLUX 版 LoRA（FLUX 模型不能叠加 SDXL/SD1.5 LoRA）", len(dropped)
        )
    return kept


@register("flux_txt2img")
def build_flux_txt2img(
    unet_name: str | None = None,
    clip_name: str | None = None,
    clip_name2: str | None = None,
    clip_type: str | None = None,
    vae_name: str | None = None,
    guidance: float | None = None,
    prompt: str = "",
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 1.0,
    sampler: str = "euler",
    scheduler: str = "simple",
    seed: int = -1,
    batch_size: int = 1,
    filename_prefix: str = "MPWE",
    hires_fix: bool = False,
    upscale_model: str = "",
    hires_denoise: float = 0.45,
    hires_steps: int = 0,
    hires_cfg: float = 0.0,
    face_detailer: bool = False,
    face_detector: str = "bbox/face_yolov8m.pt",
    face_threshold: float = 0.5,
    face_denoise: float = 0.35,
    face_steps: int = 16,
    face_cfg: float = 5.0,
    face_guide_size: float = 512,
    face_max_size: float = 1024,
    loras: list | None = None,
    **_extra: Any,
) -> dict:
    """FLUX.1-dev（GGUF 量化）文生图。"""
    if not unet_name:
        raise ValueError("flux_txt2img 需要 unet_name（GGUF 扩散模型文件名）")

    preset = get_diffusion_preset(unet_name) or {}
    resolved = {
        "clip_name": clip_name or preset.get("clip_name"),
        "clip_name2": clip_name2 or preset.get("clip_name2"),
        "clip_type": clip_type or preset.get("clip_type", "flux"),
        "vae_name": vae_name or preset.get("vae_name"),
        "guidance": float(preset.get("guidance", 3.5)) if guidance is None else float(guidance),
        "latent_node": preset.get("latent_node", "EmptySD3LatentImage"),
    }
    if not resolved["clip_name"] or not resolved["clip_name2"] or not resolved["vae_name"]:
        raise ValueError(
            f"未找到模型 {unet_name} 的官方预设（FLUX 需要 clip_name / clip_name2 / vae_name）"
        )
    if seed is None or seed < 0:
        seed = random.randint(0, 2**32 - 1)

    graph: dict[str, Any] = {
        # GGUF 量化 UNET（需要 ComfyUI-GGUF 节点）
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet_name}},
        # 双文本编码器：clip_l + t5xxl（type=flux）
        "2": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": resolved["clip_name"],
                "clip_name2": resolved["clip_name2"],
                "type": resolved["clip_type"],
            },
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": resolved["vae_name"]}},
        "4": {
            "class_type": resolved["latent_node"],
            "inputs": {"width": int(width), "height": int(height), "batch_size": int(batch_size)},
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative_prompt}},
        # FLUX 的引导强度走 FluxGuidance（不是 CFG）
        "11": {
            "class_type": "FluxGuidance",
            "inputs": {"conditioning": ["5", 0], "guidance": resolved["guidance"]},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["11", 0],
                "negative": ["6", 0],
                "latent_image": ["4", 0],
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
            },
        },
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "10": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix or "MPWE", "images": ["9", 0]},
        },
    }

    # ---------------- LoRA 叠加（只接受 FLUX 版 LoRA） ----------------
    model_ref, clip_ref = attach_loras(graph, ["1", 0], ["2", 0], _flux_only_loras(loras))
    graph["7"]["inputs"]["model"] = model_ref
    graph["5"]["inputs"]["clip"] = clip_ref
    graph["6"]["inputs"]["clip"] = clip_ref

    # ---------------- 画质增强（超分重绘 / 脸部修复） ----------------
    final_image_node = attach_quality_stage(
        graph,
        model_ref=model_ref,
        clip_ref=clip_ref,
        vae_ref=["3", 0],
        positive_ref=["11", 0],
        negative_ref=["6", 0],
        image_node="9",
        seed=seed,
        sampler=sampler,
        scheduler=scheduler,
        steps=steps,
        cfg=cfg,
        hires_fix=hires_fix,
        upscale_model=upscale_model,
        hires_denoise=hires_denoise,
        hires_steps=hires_steps,
        hires_cfg=hires_cfg,
        face_detailer=face_detailer,
        face_detector=face_detector,
        face_threshold=face_threshold,
        face_denoise=face_denoise,
        face_steps=face_steps,
        face_cfg=face_cfg,
        face_guide_size=face_guide_size,
        face_max_size=face_max_size,
    )
    graph["10"]["inputs"]["images"] = [final_image_node, 0]
    return graph


__all__ = ["build_flux_txt2img"]
