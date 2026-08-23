"""模型预设加载器。

所有预设数据存放在项目根目录 `model_configs/` 下的 YAML 文件中
（参数来源：各模型官方仓库/官方工作流文档），本模块负责读取并扁平化。
新增模型时只需在 `model_configs/` 加一个 YAML 文件，无需改代码。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

MODEL_CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent / "model_configs"
logger = logging.getLogger(__name__)


def _load_all() -> dict[str, dict]:
    """读取 model_configs 目录下全部 YAML，返回 {model_file: 配置}。"""
    configs: dict[str, dict] = {}
    if not MODEL_CONFIGS_DIR.exists():
        return configs
    for path in sorted(MODEL_CONFIGS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("模型配置文件解析失败，已跳过: %s", path.name)
            continue
        if isinstance(data, dict) and data.get("model_file"):
            configs[data["model_file"]] = data
    return configs


def _flatten(cfg: dict) -> dict:
    """把配置拍平成前端/构建器可直接使用的 dict（params 提到顶层）。"""
    flattened = dict(cfg.get("params") or {})
    flattened.update(cfg.get("prompt") or {})
    flattened["name"] = cfg.get("name", "")
    flattened["workflow"] = cfg.get("workflow", "")
    flattened["category"] = cfg.get("category", "")
    flattened["source"] = cfg.get("source", "")
    flattened["negative_default"] = cfg.get("negative_default", "")
    flattened["quality"] = cfg.get("quality") or {}
    flattened["loras"] = cfg.get("loras") or []
    flattened["resolution_presets"] = cfg.get("resolution_presets") or []
    flattened["note"] = f"{cfg.get('name', '')}：官方预设（{cfg.get('source', '')}）"
    return flattened


_ALL = _load_all()

DIFFUSION_PRESETS: dict[str, dict] = {
    model_file: _flatten(cfg)
    for model_file, cfg in _ALL.items()
    if cfg.get("category") == "diffusion_models"
}

CHECKPOINT_PRESETS: dict[str, dict] = {
    model_file: _flatten(cfg)
    for model_file, cfg in _ALL.items()
    if cfg.get("category") == "checkpoints"
}


def get_diffusion_preset(unet_name: str) -> dict | None:
    """按扩散模型文件名返回预设（已扁平化），未收录时返回 None。"""
    return DIFFUSION_PRESETS.get(unet_name)


def get_checkpoint_preset(checkpoint_name: str) -> dict | None:
    """按 Checkpoint 模型文件名返回预设，未收录时返回 None。"""
    return CHECKPOINT_PRESETS.get(checkpoint_name)
