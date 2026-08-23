"""AI Agent 提示词配置的读取与在线编辑（ruamel 保注释回写）。

管理后台直接编辑 app/prompting/agent_prompts.yaml 里的 Agent 提示词，
写入后运行时 loader 按 mtime 自动重载，无需重启。
"""

from __future__ import annotations

import threading
import os
from pathlib import Path

from ruamel.yaml import YAML

_DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent.parent / "prompting" / "agent_prompts.yaml"
PROMPTS_PATH = Path(os.getenv("MPWE_PROMPTS_PATH") or _DEFAULT_PROMPTS_PATH)

_lock = threading.Lock()


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _load_doc(path: Path = PROMPTS_PATH):
    return _yaml().load(path.read_text(encoding="utf-8"))


def _locate(doc, agent_id: str):
    """按 agent_id 定位节点：expand_agent / translate_agent:<model_file>。"""
    if agent_id == "expand_agent":
        return doc.get("expand_agent")
    prefix = "translate_agent:"
    if agent_id.startswith(prefix):
        model_file = agent_id[len(prefix):]
        entry = (doc.get("models") or {}).get(model_file)
        if entry:
            return entry.get("translate_agent")
    return None


def _agent_dict(agent_id: str, node: dict) -> dict:
    model_file = ""
    if agent_id.startswith("translate_agent:"):
        model_file = agent_id[len("translate_agent:"):]
    return {
        "id": agent_id,
        "model_file": model_file,
        "name": node.get("name", ""),
        "description": node.get("description", ""),
        "prompt": node.get("prompt", ""),
    }


def list_agents(path: Path = PROMPTS_PATH) -> list[dict]:
    """列出全部可编辑 Agent（共用扩写 Agent + 各模型专属翻译 Agent）。"""
    doc = _load_doc(path)
    agents: list[dict] = []
    exp = doc.get("expand_agent") or {}
    if exp.get("prompt"):
        agents.append(_agent_dict("expand_agent", exp))
    for model_file, entry in (doc.get("models") or {}).items():
        ta = (entry or {}).get("translate_agent") or {}
        if ta.get("prompt"):
            agents.append(_agent_dict(f"translate_agent:{model_file}", ta))
    return agents


def get_agent(agent_id: str, path: Path = PROMPTS_PATH) -> dict | None:
    doc = _load_doc(path)
    node = _locate(doc, agent_id)
    if node is None or not node.get("prompt"):
        return None
    return _agent_dict(agent_id, node)


def update_agent(
    agent_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
    path: Path = PROMPTS_PATH,
) -> dict:
    """更新 Agent 的 name/description/prompt 并回写 YAML（保留注释与格式）。"""
    with _lock:
        doc = _load_doc(path)
        node = _locate(doc, agent_id)
        if node is None:
            raise KeyError(agent_id)
        if name is not None:
            name = (name or "").strip()
            if not name:
                raise ValueError("Agent 名字不能为空")
            node["name"] = name
        if description is not None:
            node["description"] = (description or "").strip()
        if prompt is not None:
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("提示词不能为空")
            node["prompt"] = prompt
        # 必须显式 UTF-8 流输出：直接 dump 到 Path 会按系统 ANSI（Windows 上为 GBK）写坏中文注释
        with path.open("w", encoding="utf-8") as fh:
            _yaml().dump(doc, fh)
        return _agent_dict(agent_id, node)


__all__ = ["PROMPTS_PATH", "list_agents", "get_agent", "update_agent"]
