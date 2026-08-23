"""扩散模型文生图功能（UNET + CLIP + VAE）：Z-Image / Anima 系列。"""

from __future__ import annotations

import random
from typing import Any

from app.comfyui.presets import get_diffusion_preset

from .loras import attach_loras
from .quality import attach_quality_stage
from .registry import register


def build_diffusion_txt2img(
    *,
    unet_name: str,
    clip_name: str,
    clip_type: str,
    vae_name: str,
    latent_node: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    scheduler: str,
    seed: int,
    batch_size: int,
    filename_prefix: str,
    model_shift: float = 0.0,
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
) -> dict:
    """通用扩散模型（UNET + CLIP + VAE）文生图图构建。

    结构：UNETLoader -> [ModelSamplingAuraFlow?] -> LoRA 链 -> KSampler
          CLIPLoader -> CLIPTextEncode x2 -> KSampler
          VAELoader -> VAEDecode -> 画质增强 -> SaveImage
    """
    if seed is None or seed < 0:
        seed = random.randint(0, 2**32 - 1)

    graph: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet_name, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip_name, "type": clip_type, "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
        "4": {
            "class_type": latent_node,
            "inputs": {"width": int(width), "height": int(height), "batch_size": int(batch_size)},
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative_prompt}},
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0] if model_shift <= 0 else ["8", 0],
                "positive": ["5", 0],
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
    if model_shift > 0:
        graph["8"] = {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["1", 0], "shift": float(model_shift)},
        }
    # ---------------- LoRA 叠加阶段 ----------------
    model_ref = ["8", 0] if model_shift > 0 else ["1", 0]
    model_ref, clip_ref = attach_loras(graph, model_ref, ["2", 0], loras)
    graph["7"]["inputs"]["model"] = model_ref
    graph["5"]["inputs"]["clip"] = clip_ref
    graph["6"]["inputs"]["clip"] = clip_ref

    # ---------------- 画质增强阶段 ----------------
    final_image_node = attach_quality_stage(
        graph,
        model_ref=model_ref,
        clip_ref=clip_ref,
        vae_ref=["3", 0],
        positive_ref=["5", 0],
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


@register("z_image_txt2img")
def build_z_image_txt2img(
    unet_name: str | None = None,
    clip_name: str | None = None,
    clip_type: str | None = None,
    vae_name: str | None = None,
    model_shift: float | None = None,
    prompt: str = "",
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1536,
    steps: int = 10,
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
    """Z-Image 系列文生图（z_image_turbo / z-anime-distill）。"""
    if not unet_name:
        raise ValueError("z_image_txt2img 需要 unet_name（扩散模型文件名）")
    preset = get_diffusion_preset(unet_name) or {}
    resolved = {
        "clip_name": clip_name or preset.get("clip_name"),
        "clip_type": clip_type or preset.get("clip_type", "lumina2"),
        "vae_name": vae_name or preset.get("vae_name"),
        "model_shift": preset.get("model_shift", 3.0) if model_shift is None else model_shift,
        "latent_node": preset.get("latent_node", "EmptySD3LatentImage"),
    }
    if not resolved["clip_name"] or not resolved["vae_name"]:
        raise ValueError(
            f"未找到模型 {unet_name} 的官方预设，请提供 clip_name 与 vae_name"
        )
    return build_diffusion_txt2img(
        unet_name=unet_name,
        clip_name=resolved["clip_name"],
        clip_type=resolved["clip_type"],
        vae_name=resolved["vae_name"],
        latent_node=resolved["latent_node"],
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        scheduler=scheduler,
        seed=seed,
        batch_size=batch_size,
        filename_prefix=filename_prefix,
        model_shift=resolved["model_shift"],
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
        loras=loras,
    )


@register("anima_txt2img")
def build_anima_txt2img(
    unet_name: str | None = None,
    clip_name: str | None = None,
    clip_type: str | None = None,
    vae_name: str | None = None,
    model_shift: float | None = None,
    prompt: str = "",
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 30,
    cfg: float = 4.0,
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
    """Anima 系列文生图（anima-aesthetic 等，2B 动漫模型）。"""
    if not unet_name:
        raise ValueError("anima_txt2img 需要 unet_name（扩散模型文件名）")
    preset = get_diffusion_preset(unet_name) or {}
    resolved = {
        "clip_name": clip_name or preset.get("clip_name"),
        "clip_type": clip_type or preset.get("clip_type", "stable_diffusion"),
        "vae_name": vae_name or preset.get("vae_name"),
        "model_shift": preset.get("model_shift", 0.0) if model_shift is None else model_shift,
        "latent_node": preset.get("latent_node", "EmptyLatentImage"),
    }
    if not resolved["clip_name"] or not resolved["vae_name"]:
        raise ValueError(
            f"未找到模型 {unet_name} 的官方预设，请提供 clip_name 与 vae_name"
        )
    return build_diffusion_txt2img(
        unet_name=unet_name,
        clip_name=resolved["clip_name"],
        clip_type=resolved["clip_type"],
        vae_name=resolved["vae_name"],
        latent_node=resolved["latent_node"],
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        scheduler=scheduler,
        seed=seed,
        batch_size=batch_size,
        filename_prefix=filename_prefix,
        model_shift=resolved["model_shift"],
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
        loras=loras,
    )
