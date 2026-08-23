"""画质增强功能：超分放大重绘（Hires fix）+ 脸部修复（FaceDetailer）。"""

from __future__ import annotations

from typing import Any


def attach_quality_stage(
    graph: dict[str, Any],
    *,
    model_ref: list,
    clip_ref: list,
    vae_ref: list,
    positive_ref: list,
    negative_ref: list,
    image_node: str,
    seed: int,
    sampler: str,
    scheduler: str,
    steps: int,
    cfg: float,
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
) -> str:
    """在任意文生图图上追加「超分放大重绘 + 脸部修复」阶段，返回最终图像节点 id。

    固定使用 20-24（超分链）与 30-31（脸部修复）作为节点号，
    与各基础工作流的节点号不冲突（基础图使用 1-11）。
    """
    final_image_node = image_node

    if hires_fix:
        if not upscale_model:
            raise ValueError("启用超分放大重绘时，必须指定 upscale_model（如 2x_IllustrationJaNai_...）")
        hires_cfg = float(hires_cfg or cfg)
        hires_steps = int(hires_steps or steps)
        graph["20"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": upscale_model},
        }
        graph["21"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["20", 0], "image": [final_image_node, 0]},
        }
        graph["22"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["21", 0], "vae": vae_ref},
        }
        graph["23"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": model_ref,
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["22", 0],
                "seed": int(seed),
                "steps": hires_steps,
                "cfg": float(hires_cfg),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": float(hires_denoise),
            },
        }
        graph["24"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["23", 0], "vae": vae_ref},
        }
        final_image_node = "24"

    if face_detailer:
        graph["30"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": face_detector},
        }
        graph["31"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": [final_image_node, 0],
                "model": model_ref,
                "clip": clip_ref,
                "vae": vae_ref,
                "guide_size": float(face_guide_size),
                "guide_size_for": True,
                "max_size": float(face_max_size),
                "seed": int(seed),
                "steps": int(face_steps),
                "cfg": float(face_cfg),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "positive": positive_ref,
                "negative": negative_ref,
                "denoise": float(face_denoise),
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": float(face_threshold),
                "bbox_dilation": 10,
                "bbox_crop_factor": 3.0,
                "sam_detection_hint": "none",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "bbox_detector": ["30", 0],
                "wildcard": "",
                "cycle": 1,
            },
        }
        final_image_node = "31"

    return final_image_node
