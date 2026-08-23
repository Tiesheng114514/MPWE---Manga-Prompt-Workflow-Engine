"""文生图功能（Checkpoint 模型）：加载底模 -> LoRA 链 -> 采样 -> 画质增强 -> 保存。"""

from __future__ import annotations

import random
from typing import Any

from .loras import attach_loras
from .quality import attach_quality_stage
from .registry import register


@register("txt2img")
def build_txt2img(
    checkpoint: str,
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 6.0,
    sampler: str = "euler",
    scheduler: str = "normal",
    seed: int = -1,
    batch_size: int = 1,
    filename_prefix: str = "MPWE",
    clip_skip: int = 0,
    # 画质增强：超分放大重绘 + 脸部修复
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
    # LoRA 叠加
    loras: list | None = None,
    **_extra: Any,
) -> dict:
    """文生图：Checkpoint 加载 -> LoRA 链 -> 双 CLIP 编码 -> KSampler -> 画质增强 -> 保存。"""
    if seed is None or seed < 0:
        seed = random.randint(0, 2**32 - 1)
    clip_ref = ["11", 0] if clip_skip > 0 else ["4", 1]
    graph: dict[str, Any] = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": int(width),
                "height": int(height),
                "batch_size": int(batch_size),
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": clip_ref, "text": prompt},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": clip_ref, "text": negative_prompt},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": filename_prefix or "MPWE",
                "images": ["8", 0],
            },
        },
    }
    if clip_skip > 0:
        graph["11"] = {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["4", 1], "stop_at_clip_layer": -abs(int(clip_skip))},
        }

    # ---------------- LoRA 叠加阶段 ----------------
    model_ref, clip_ref = attach_loras(graph, ["4", 0], clip_ref, loras)
    graph["3"]["inputs"]["model"] = model_ref
    graph["6"]["inputs"]["clip"] = clip_ref
    graph["7"]["inputs"]["clip"] = clip_ref

    # ---------------- 画质增强阶段 ----------------
    final_image_node = attach_quality_stage(
        graph,
        model_ref=model_ref,
        clip_ref=clip_ref,
        vae_ref=["4", 2],
        positive_ref=["6", 0],
        negative_ref=["7", 0],
        image_node="8",
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
    graph["9"]["inputs"]["images"] = [final_image_node, 0]
    return graph
