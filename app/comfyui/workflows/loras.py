"""LoRA 叠加功能：把多个 LoRA 串成 LoraLoader 链。"""

from __future__ import annotations

from typing import Any


def attach_loras(
    graph: dict[str, Any],
    model_ref: list,
    clip_ref: list,
    loras: list | None,
    start_id: int = 40,
) -> tuple[list, list]:
    """按顺序把 LoRA 串成 LoraLoader 链，返回 (最终 model 引用, 最终 clip 引用)。

    每个 LoRA 一个 LoraLoader 节点：model/clip 依次从前一个节点输出取。
    权重 0 或空文件名的条目会被跳过。
    """
    if not loras:
        return model_ref, clip_ref
    node_id = start_id
    for item in loras:
        if not isinstance(item, dict):
            continue
        file_name = item.get("file") or item.get("name") or ""
        try:
            weight = float(item.get("weight", 0.6))
        except (TypeError, ValueError):
            weight = 0.6
        if not file_name or weight == 0:
            continue
        graph[str(node_id)] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model_ref,
                "clip": clip_ref,
                "lora_name": file_name,
                "strength_model": weight,
                "strength_clip": weight,
            },
        }
        model_ref = [str(node_id), 0]
        clip_ref = [str(node_id), 1]
        node_id += 1
    return model_ref, clip_ref
