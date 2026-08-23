"""OpenAI 兼容 LLM 客户端（默认 DeepSeek）。"""

from __future__ import annotations

import logging

from openai import APITimeoutError, APIError, AuthenticationError, OpenAI

from app.config import load_config

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """LLM 配置缺失或 Key 无效。"""


class LLMTimeoutError(RuntimeError):
    """LLM 请求超时。"""


class LLMAPIError(RuntimeError):
    """LLM API 调用失败。"""


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        cfg = load_config().get("llm") or {}
        api_key = (cfg.get("api_key") or "").strip()
        if not api_key:
            raise LLMConfigError(
                "未配置 LLM API Key：请在项目根目录 .env 中设置 OPENAI_API_KEY（可参考 .env.example）"
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=cfg.get("base_url") or "https://api.deepseek.com",
            timeout=float(cfg.get("timeout") or 120),
        )
    return _client


def chat(
    system: str,
    user: str,
    temperature: float = 0.4,
    max_tokens: int = 4000,
    on_usage=None,
) -> str:
    """调用 LLM 完成一次对话，返回 assistant 文本。

    on_usage 可选：每次调用结束后回调 {prompt_tokens, completion_tokens,
    total_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens}，用于实时计费。
    """
    cfg = load_config().get("llm") or {}
    client = _get_client()
    kwargs = {}
    if cfg.get("disable_thinking", True):
        # DeepSeek 专用：关闭思考链，降低延迟与成本
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        resp = client.chat.completions.create(
            model=cfg.get("model") or "deepseek-v4-flash",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens or 4000,
            **kwargs,
        )
    except AuthenticationError as exc:
        raise LLMConfigError(f"LLM API Key 无效或未授权: {exc}") from exc
    except APITimeoutError as exc:
        raise LLMTimeoutError(f"LLM 请求超时: {exc}") from exc
    except APIError as exc:
        raise LLMAPIError(f"LLM API 调用失败: {exc}") from exc
    content = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    if on_usage is not None and usage is not None:
        on_usage(
            {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                "prompt_cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", None),
                "prompt_cache_miss_tokens": getattr(usage, "prompt_cache_miss_tokens", None),
            }
        )
    return content
