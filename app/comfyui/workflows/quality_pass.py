"""二次创作功能：对已生成的图片做画质增强（超分放大重绘 + 脸部修复）。

与 txt2img 内置画质阶段不同，本工作流以「已有图片」为输入：
LoadImage -> [LoRA 链] -> 超分放大 -> VAEEncode -> 低降噪重绘 -> 脸部修复 -> 保存。
"""

from __future__ import annotations

import random
from typing import Any

from .loras import attach_loras
from .quality import attach_quality_stage
from .registry import register


@register("quality_pass")
def build_quality_pass(
    checkpoint: str,
    prompt: str,
    negative_prompt: str = "",
    image_filename: str = "",
    steps: int = 20,
    cfg: float = 6.0,
    sampler: str = "euler",
    scheduler: str = "normal",
    seed: int = -1,
    filename_prefix: str = "MPWE_quality",
    clip_skip: int = 0,
    # 画质增强
    hires_fix: bool = True,
    upscale_model: str = "",
    hires_denoise: float = 0.45,
    hires_steps: int = 0,
    hires_cfg: float = 0.0,
    face_detailer: bool = True,
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
    """图生图质量增强：加载已有图片 -> 超分重绘 -> 脸部修复 -> 保存。"""
    if not image_filename:
        raise ValueError("quality_pass 需要 image_filename（已生成图片的文件名）")
    if hires_fix and not upscale_model:
        raise ValueError("启用超分放大重绘时，必须指定 upscale_model（如 2x_IllustrationJaNai_...）")
    if seed is None or seed < 0:
        seed = random.randint(0, 2**32 - 1)
    clip_ref = ["5", 0] if clip_skip > 0 else ["2", 1]
    graph: dict[str, Any] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": prompt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": negative_prompt}},
    }
    if clip_skip > 0:
        graph["5"] = {
            "class_type": "CLIPSetLastLayer",
            "inputs": {"clip": ["2", 1], "stop_at_clip_layer": -abs(int(clip_skip))},
        }

    # ---------------- LoRA 叠加阶段 ----------------
    model_ref, clip_ref = attach_loras(graph, ["2", 0], clip_ref, loras)
    graph["3"]["inputs"]["clip"] = clip_ref
    graph["4"]["inputs"]["clip"] = clip_ref

    # ---------------- 画质增强阶段（输入 = LoadImage） ----------------
    final_image_node = attach_quality_stage(
        graph,
        model_ref=model_ref,
        clip_ref=clip_ref,
        vae_ref=["2", 2],
        positive_ref=["3", 0],
        negative_ref=["4", 0],
        image_node="1",
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
    graph["10"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": filename_prefix or "MPWE_quality",
            "images": [final_image_node, 0],
        },
    }
    return graph
