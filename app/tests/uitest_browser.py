"""WebUI 真实浏览器点击测试（Playwright + 系统 Edge，无头模式）。

覆盖：AI 提示词 Agent 生成、出图进度条、占位符隐藏、图片容器适配、点击放大灯箱。
用法：.venv\\Scripts\\python.exe app\\tests\\uitest_browser.py
（若 8642 无后端则自动拉起一个，测试后保持运行；已有后端则直接复用。）
依赖：pip install playwright（国内可用清华镜像），浏览器复用系统 Edge。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(PROJ, ".venv", "Scripts", "python.exe")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://127.0.0.1:8642"
SHOTS = os.path.join(PROJ, "data", "uitest")
os.makedirs(SHOTS, exist_ok=True)

sys.path.insert(0, PROJ)


def wait_health(timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/mpwe/health", timeout=3) as r:
                return r.status == 200
        except Exception:
            time.sleep(0.5)
    return False


def main() -> None:
    server = None
    if not wait_health(timeout=3):
        print("8642 无后端，自动拉起…", flush=True)
        server = subprocess.Popen(
            [PY, "-m", "app.main"],
            cwd=PROJ,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_health():
            print("后端启动失败", flush=True)
            server.terminate()
            sys.exit(1)
    print("后端已就绪", flush=True)

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=EDGE,
                headless=True,
                args=["--disable-features=msEdgeFirstRunExperience"],
            )
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            results: list[tuple[str, bool, str]] = []

            def check(name: str, cond: bool, detail: str = "") -> None:
                results.append((name, cond, detail))
                print(("[PASS] " if cond else "[FAIL] ") + name + (f"  ({detail})" if detail else ""), flush=True)

            page.goto(BASE, wait_until="networkidle", timeout=30000)
            page.wait_for_function(
                "document.querySelector('#checkpoint') && document.querySelector('#checkpoint').value === 'one obsession_v14.safetensors'",
                timeout=20000,
            )
            check("页面加载 / V14 默认选中", page.input_value("#checkpoint") == "one obsession_v14.safetensors")
            check("Agent 按钮可用（V14 已适配）", page.is_enabled("#agent-btn"))
            page.screenshot(path=os.path.join(SHOTS, "01_initial.png"))

            check("初始占位符可见", page.is_visible("#result-placeholder"))

            # 1) AI 提示词 Agent
            page.fill("#agent_input", "雨夜一个女生撑着透明伞站在路灯下，半身构图，要有氛围感")
            page.click("#agent-btn")
            page.wait_for_selector("#agent-status:has-text('已由')", timeout=90000)
            agent_status = page.text_content("#agent-status") or ""
            pos_val = page.input_value("#prompt")
            neg_val = page.input_value("#negative_prompt")
            check("Agent 生成完成并回填正/负向", bool(pos_val.strip()) and bool(neg_val.strip()), agent_status)
            check("回填内容全英文", not any("\u4e00" <= ch <= "\u9fff" for ch in pos_val))
            check("回填含官方质量词", "masterpiece" in pos_val and "very awa" in pos_val)
            page.screenshot(path=os.path.join(SHOTS, "02_agent_done.png"))

            # 2) 出图 + 进度条
            page.click("#generate-btn")
            progress_seen = False
            max_pct = 0
            deadline = time.time() + 240
            while time.time() < deadline and not page.is_visible("#result-image"):
                if page.is_visible("#progress-wrap"):
                    pct_txt = page.text_content("#progress-text") or ""
                    pct = 0
                    if "%" in pct_txt:
                        try:
                            pct = int(pct_txt.split("%")[0].split()[-1])
                        except Exception:
                            pass
                    if pct > max_pct:
                        max_pct = pct
                    if not progress_seen and pct > 0:
                        progress_seen = True
                        page.screenshot(path=os.path.join(SHOTS, "03_progress.png"))
                time.sleep(0.8)
            check("出图任务出现进度条且前进", progress_seen and max_pct > 0, f"max={max_pct}%")

            page.wait_for_selector("#result-image:not([hidden])", timeout=60000)
            page.wait_for_function("document.querySelector('#result-image').complete && document.querySelector('#result-image').naturalWidth > 0", timeout=30000)
            check("占位符已隐藏", page.is_hidden("#result-placeholder"))
            check("进度条已隐藏（完成）", page.is_hidden("#progress-wrap"))
            page.screenshot(path=os.path.join(SHOTS, "04_result.png"))

            # 图片容器适配：竖图应完整显示在框内（不裁切、不贴边）
            box = page.evaluate(
                """() => {
                  const img = document.querySelector('#result-image');
                  const box = document.querySelector('#result-box');
                  const ir = img.getBoundingClientRect();
                  const br = box.getBoundingClientRect();
                  return { naturalW: img.naturalWidth, naturalH: img.naturalHeight,
                           imgW: ir.width, imgH: ir.height,
                           boxW: br.width, boxH: br.height,
                           fit: ir.width <= br.width - 10 && ir.height <= br.height - 10 };
                }"""
            )
            check("竖图完整显示在容器内", box["naturalH"] > box["naturalW"] and box["fit"],
                  f"{box['naturalW']}x{box['naturalH']} -> {box['imgW']:.0f}x{box['imgH']:.0f} in {box['boxW']:.0f}x{box['boxH']:.0f}")

            # 3) 点击放大
            page.click("#result-image")
            page.wait_for_selector("#lightbox:not([hidden])", timeout=5000)
            check("点击图片打开放大灯箱", page.is_visible("#lightbox-img"))
            page.screenshot(path=os.path.join(SHOTS, "05_lightbox.png"))
            page.keyboard.press("Escape")
            check("Esc 关闭灯箱", page.is_hidden("#lightbox"))

            browser.close()
    finally:
        if server is not None and server.poll() is None:
            print(f"后端保持运行（PID={server.pid}）", flush=True)

    failed = [r for r in results if not r[1]]
    print(("\nUI TEST: %d/%d PASS" % (len(results) - len(failed), len(results))), flush=True)
    if failed:
        sys.exit(1)
    print(f"截图目录: {SHOTS}", flush=True)


if __name__ == "__main__":
    main()
