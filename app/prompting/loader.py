"""AI Agent 提示词配置加载器。

读取 app/prompting/agent_prompts.yaml，带 mtime 缓存：
修改配置文件后无需重启，下一次请求自动生效。
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROMPTS_PATH = Path(__file__).resolve().parent / "agent_prompts.yaml"

_cache: dict = {"mtime": None, "data": None}


class PromptConfigError(RuntimeError):
    """提示词配置缺失或格式错误。"""


def _load() -> dict:
    """读取配置文件（带 mtime 缓存）。"""
    mtime = PROMPTS_PATH.stat().st_mtime_ns if PROMPTS_PATH.exists() else None
    if _cache["data"] is not None and _cache["mtime"] == mtime:
        return _cache["data"]
    if not PROMPTS_PATH.exists():
        raise PromptConfigError(f"AI Agent 提示词配置不存在: {PROMPTS_PATH}")
    try:
        data = yaml.safe_load(PROMPTS_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PromptConfigError(f"AI Agent 提示词配置解析失败（{PROMPTS_PATH.name}）: {exc}") from exc
    if not isinstance(data, dict):
        raise PromptConfigError("AI Agent 提示词配置格式错误：顶层必须是映射")
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def get_expand_agent() -> dict:
    """返回共用扩写 Agent（阶段一，所有模型一样）。"""
    data = _load()
    agent = data.get("expand_agent") or {}
    if not agent.get("prompt"):
        raise PromptConfigError("配置缺少 expand_agent（共用扩写 Agent）")
    return agent


def get_translate_agent(model_file: str) -> dict | None:
    """按 model_file 精确匹配翻译 Agent（阶段二）。

    严格一对一：只在 models 列表里配置过的模型返回 Agent，
    未配置返回 None（不存在通用回退，避免提示词与模型混用）。
    """
    data = _load()
    entry = (data.get("models") or {}).get(model_file or "") or {}
    agent = entry.get("translate_agent") or {}
    if agent.get("prompt"):
        return agent
    return None


def get_supported_agents() -> dict[str, str]:
    """返回 {model_file: agent_name}：所有已配置专属翻译 Agent 的模型。"""
    data = _load()
    agents: dict[str, str] = {}
    for model_file, entry in (data.get("models") or {}).items():
        ta = (entry or {}).get("translate_agent") or {}
        if ta.get("prompt"):
            agents[model_file] = ta.get("name", model_file)
    return agents


def get_default_validation() -> dict:
    """返回通用回退校验参数。"""
    data = _load()
    return data.get("default_validation") or {}
