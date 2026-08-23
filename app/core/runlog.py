"""项目整体运行日志（JSONL）。

记录每一次生成 / API 调用 / 充值的：时间、用户、算力消耗、费用，供日后统计与排查。
文件：data/logs/run_history.jsonl（已被 .gitignore 排除，不会提交）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = PROJECT_ROOT / "data" / "logs" / "run_history.jsonl"

_lock = threading.Lock()


def append_run(entry: dict) -> None:
    """追加一条运行记录（线程安全）。"""
    entry = dict(entry)
    entry.setdefault("ts", round(time.time(), 3))
    with _lock:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_history_path() -> Path:
    return LOG_PATH


__all__ = ["append_run", "run_history_path"]
