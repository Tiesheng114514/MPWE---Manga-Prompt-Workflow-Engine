"""冒烟测试：启动后端（临时 DB / 测试端口），验证健康检查与队列接口，随后关闭。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPWE_DB_PATH", str(Path(tempfile.mkdtemp(prefix="mpwe_smoke_")) / "mpwe.db"))
os.environ.setdefault("MPWE_PORT", "8650")

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402


def _get(url: str, timeout: float = 8.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    port = int(os.environ["MPWE_PORT"])
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline and not server.started:
        time.sleep(0.1)
    if not server.started:
        print("服务器启动失败")
        return 1
    try:
        health = _get(f"http://127.0.0.1:{port}/mpwe/health")
        queue = _get(f"http://127.0.0.1:{port}/mpwe/queue")
        try:
            _get(f"http://127.0.0.1:{port}/mpwe/jobs")
            jobs_status = "unexpected-200"
        except urllib.error.HTTPError as exc:
            jobs_status = f"401-as-expected" if exc.code == 401 else f"unexpected-{exc.code}"
        print("health:", json.dumps(health, ensure_ascii=False))
        print("queue :", json.dumps(queue, ensure_ascii=False))
        print("jobs  :", jobs_status)
        assert health.get("status") == "ok"
        assert "workers" in queue and "queued" in queue
        assert jobs_status == "401-as-expected"
        print("SMOKE OK")
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
