"""全局配置加载。

优先级：环境变量 > config.yaml > 内置默认值。
支持的环境变量：
  - MPWE_HOST          服务监听地址
  - MPWE_PORT          服务端口
  - COMFYUI_BASE_URL   ComfyUI 地址（如 http://127.0.0.1:8188）
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 项目根目录（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

load_dotenv(PROJECT_ROOT / ".env")

_DEFAULTS: dict = {
    "server": {"host": "127.0.0.1", "port": 8642},
    "admin": {"host": "127.0.0.1", "port": 8643},
    "comfyui": {
        "base_url": "http://127.0.0.1:8188",
        "client_id": "mpwe-webui",
        "timeout": 30,
        "workers": None,  # 并行实例列表；缺省回退为 [base_url]
    },
    "queue": {
        "max_concurrent_per_user": 2,   # 每用户最多同时运行几个任务（防单用户占满队列）
        "poll_interval_s": 0.5,         # 调度器轮询间隔
        "max_queue_dispatch": 50,       # 每轮最多尝试派发多少个排队任务
        "worker_down_grace_s": 30,      # 实例提交失败后的临时拉黑时长
        "max_dispatch_attempts": 3,     # 连续提交失败多少次后任务判失败
    },
    "vram": {
        "estimates_file": "",           # 空 = data/vram_estimates.json
        "total_vram_mb": 0,             # 0 = 用估算表里的 GPU 值
        "headroom_mb": 0,               # 0 = 用估算表里的余量
    },
    "llm": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "timeout": 120,
        "max_tokens": 4000,
        "disable_thinking": True,
    },
    "turnstile": {
        "enabled": True,
        "site_key": "",
        "secret_key": "",
    },
    "billing": {
        "api": {
            # 元 / 百万 tokens；高峰时段为闲时 2 倍（DeepSeek V4 Flash 官方 2026-08-17 起）
            "peak_hours": [[9, 12], [14, 18]],
            "off_peak": {"input_cache_hit": 0.05, "input_cache_miss": 1.5, "output": 4.5},
            "peak": {"input_cache_hit": 0.10, "input_cache_miss": 3.0, "output": 9.0},
        },
        "image": {"price_per_image": 0.3},  # 元 / 张
        "signup_bonus": {"api": 0.5, "image": 3.0},  # 新用户注册赠送（API=银币，图片=金币）
        "free_recharge": {"api": 0.5, "image": 10.0},  # 免费充值额度（过验证一次性到账）
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """把 override 逐层合并到 base，返回新 dict。"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """读取配置：默认值 + config.yaml + 环境变量覆盖。"""
    config = _deep_merge({}, _DEFAULTS)
    if CONFIG_PATH.exists():
        file_config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        config = _deep_merge(config, file_config)

    if os.getenv("MPWE_HOST"):
        config["server"]["host"] = os.getenv("MPWE_HOST")
    if os.getenv("MPWE_PORT"):
        config["server"]["port"] = int(os.getenv("MPWE_PORT"))
    if os.getenv("MPWE_ADMIN_HOST"):
        config["admin"]["host"] = os.getenv("MPWE_ADMIN_HOST")
    if os.getenv("MPWE_ADMIN_PORT"):
        config["admin"]["port"] = int(os.getenv("MPWE_ADMIN_PORT"))
    if os.getenv("COMFYUI_BASE_URL"):
        config["comfyui"]["base_url"] = os.getenv("COMFYUI_BASE_URL").rstrip("/")
    workers_env = os.getenv("MPWE_COMFYUI_WORKERS", "").strip()
    if workers_env:
        parts = [u.strip() for u in workers_env.split(",") if u.strip()]
        if len(parts) == 1 and parts[0].isdigit():
            # 兼容 start_comfyui.bat：MPWE_COMFYUI_WORKERS=2 表示实例个数（8188/8189...）
            count = max(1, min(4, int(parts[0])))
            base = config["comfyui"]["base_url"].rstrip("/")
            if base.endswith(":8188"):
                config["comfyui"]["workers"] = [
                    f"http://127.0.0.1:{8187 + i}" for i in range(1, count + 1)
                ]
            else:
                config["comfyui"]["workers"] = [base] * count
        else:
            config["comfyui"]["workers"] = [u.rstrip("/") for u in parts]
    if not config["comfyui"].get("workers"):
        config["comfyui"]["workers"] = [config["comfyui"]["base_url"].rstrip("/")]
    config["comfyui"]["workers"] = [
        u.rstrip("/") for u in config["comfyui"]["workers"] if str(u).strip()
    ]

    if os.getenv("OPENAI_API_KEY"):
        config["llm"]["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_BASE_URL"):
        config["llm"]["base_url"] = os.getenv("OPENAI_BASE_URL").rstrip("/")
    if os.getenv("MPWE_LLM_MODEL"):
        config["llm"]["model"] = os.getenv("MPWE_LLM_MODEL")
    if os.getenv("MPWE_LLM_TIMEOUT"):
        config["llm"]["timeout"] = int(os.getenv("MPWE_LLM_TIMEOUT"))
    if os.getenv("MPWE_LLM_MAX_TOKENS"):
        config["llm"]["max_tokens"] = int(os.getenv("MPWE_LLM_MAX_TOKENS"))

    # Cloudflare Turnstile（Key 只从 .env / 环境变量读取，config.yaml 只控制开关）
    config["turnstile"]["site_key"] = os.getenv("TURNSTILE_SITE_KEY", "").strip()
    config["turnstile"]["secret_key"] = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if os.getenv("TURNSTILE_ENABLED", "").strip():
        config["turnstile"]["enabled"] = os.getenv("TURNSTILE_ENABLED").strip().lower() not in ("0", "false", "no")
    return config
