"""工作流注册表：集中管理所有已注册的构建函数。"""

from __future__ import annotations

from typing import Any, Callable

WORKFLOW_BUILDERS: dict[str, Callable[..., dict]] = {}


def register(name: str) -> Callable[[Callable[..., dict]], Callable[..., dict]]:
    """注册一个工作流构建函数。"""

    def decorator(fn: Callable[..., dict]) -> Callable[..., dict]:
        WORKFLOW_BUILDERS[name] = fn
        return fn

    return decorator


def list_workflows() -> list[str]:
    """列出所有已注册的工作流名称。"""
    return sorted(WORKFLOW_BUILDERS)


def build_workflow(name: str, **params: Any) -> dict:
    """按名称构建工作流图。"""
    builder = WORKFLOW_BUILDERS.get(name)
    if builder is None:
        raise KeyError(f"未注册的工作流: {name}（可用: {list_workflows()}）")
    return builder(**params)
