"""管理员后台真实浏览器点击测试 + API 冒烟（临时隐私目录/临时提示词副本，不碰真实文件）。

用法：.venv\\Scripts\\python.exe app\\tests\\uitest_admin.py
依赖：playwright（浏览器复用系统 Edge）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent.parent
PY = PROJ / ".venv" / "Scripts" / "python.exe"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = "8643"
BASE = f"http://127.0.0.1:{PORT}"
TEST_PASSWORD = "Admin@12345"
NEW_PASSWORD = "NewPass@6789"

sys.path.insert(0, str(PROJ))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mpwe_admin_test_"))
    private_dir = tmp / "private"
    prompts_copy = tmp / "agent_prompts.yaml"
    shutil.copy2(PROJ / "app" / "prompting" / "agent_prompts.yaml", prompts_copy)

    # 必须先设置环境变量再导入 secrets_store，确保测试写临时目录而非真实隐私目录
    os.environ["MPWE_PRIVATE_DIR"] = str(private_dir)
    os.environ["MPWE_PROMPTS_PATH"] = str(prompts_copy)

    env = dict(os.environ)
    env["MPWE_PRIVATE_DIR"] = str(private_dir)
    env["MPWE_PROMPTS_PATH"] = str(prompts_copy)
    env["MPWE_PORT"] = PORT

    from app.admin import secrets_store

    secrets_store.ensure_salt()
    secrets_store.set_password(TEST_PASSWORD)

    def start_server():
        proc = subprocess.Popen(
            [str(PY), "-m", "app.main"],
            cwd=str(PROJ), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ready = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                st, _, _ = api("GET", "/mpwe/health")
                if st == 200:
                    ready = True
                    break
            except Exception:
                continue
        return proc, ready

    def stop_server(proc) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    no_redirect_opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
    )
    cookie = None

    def api(method: str, path: str, payload: dict | None = None) -> tuple[int, dict, list[str]]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with opener.open(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                set_cookies = resp.headers.get_all("Set-Cookie") or []
                return resp.status, (json.loads(body) if body else {}), set_cookies
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(body), []
            except Exception:
                return e.code, {"detail": body}, []

    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, cond, detail))
        print(("[PASS] " if cond else "[FAIL] ") + name + (f"  ({detail})" if detail else ""), flush=True)

    server, ready = start_server()

    try:
        check("后端就绪", ready)

        # 未登录保护
        st, body, _ = api("GET", "/mpwe/admin/api/overview")
        check("未登录访问 overview -> 401", st == 401, str(st))
        try:
            no_redirect_opener.open(BASE + "/mpwe/admin", timeout=10)
            check("未登录访问管理页 -> 302", False)
        except urllib.error.HTTPError as e:
            check("未登录访问管理页 -> 302", e.code in (301, 302, 303), str(e.code))

        st, body, _ = api("POST", "/mpwe/admin/api/login", {"password": "wrong"})
        check("错误密码 -> 401", st == 401, body.get("detail", ""))

        st, body, cookies = api("POST", "/mpwe/admin/api/login", {"password": TEST_PASSWORD})
        check("正确密码 -> 200 并下发 Cookie", st == 200 and any("mpwe_admin=" in c for c in cookies), str(cookies)[:80])
        cookie = next(c.split(";")[0] for c in cookies if "mpwe_admin=" in c)

        st, body, _ = api("GET", "/mpwe/admin/api/overview")
        check("登录后 overview -> 200", st == 200 and body.get("llm_configured") is True, body.get("version", ""))

        st, body, _ = api("GET", "/mpwe/admin/api/prompts")
        agents = body.get("agents") or []
        check("Agent 列表 2 个", st == 200 and len(agents) == 2, str([a["id"] for a in agents]))

        v14_id = "translate_agent:one obsession_v14.safetensors"
        st, body, _ = api("PUT", f"/mpwe/admin/api/prompts/{urllib.parse.quote(v14_id)}", {"name": "One Obsession V14 Prompt Engineer (UI Edit)"})
        check("在线编辑 Agent 名字 -> 200", st == 200 and "(UI Edit)" in body.get("agent", {}).get("name", ""), str(st))

        st, body, _ = api("POST", "/mpwe/admin/api/password", {"old": TEST_PASSWORD, "new": NEW_PASSWORD})
        check("修改密码 -> 200", st == 200, str(st))
        st, _, _ = api("POST", "/mpwe/admin/api/login", {"password": TEST_PASSWORD})
        check("旧密码登录 -> 401", st == 401, str(st))
        st, body, _ = api("POST", "/mpwe/admin/api/login", {"password": NEW_PASSWORD})
        check("新密码登录 -> 200", st == 200, str(st))

        st, _, _ = api("POST", "/mpwe/admin/api/logout")
        check("退出登录 -> 200", st == 200, str(st))
        cookie = None
        st, _, _ = api("GET", "/mpwe/admin/api/overview")
        check("退出后 overview -> 401", st == 401, str(st))

        # 浏览器点击测试（重启服务，清空登录限流计数）
        stop_server(server)
        server, ready = start_server()
        check("浏览器阶段后端就绪", ready)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=EDGE,
                headless=True,
                args=["--disable-features=msEdgeFirstRunExperience"],
            )
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(BASE + "/mpwe/admin/login", wait_until="networkidle", timeout=30000)
            check("登录页加载", page.is_visible("#login-btn"))
            page.fill("#password", "wrong-pass")
            page.click("#login-btn")
            page.wait_for_selector("#login-error:not([hidden])", timeout=5000)
            check("错误密码提示", "密码错误" in (page.text_content("#login-error") or ""), page.text_content("#login-error") or "")

            page.fill("#password", NEW_PASSWORD)
            page.click("#login-btn")
            page.wait_for_selector("#logout-btn", timeout=10000)
            check("正确密码进入管理后台", page.is_visible("#overview-cards"))
            page.screenshot(path=str(tmp / "admin_dashboard.png"))

            page.click(".tab[data-tab='agents']")
            page.wait_for_selector("#agent-select option", state="attached", timeout=10000)
            page.select_option("#agent-select", v14_id)
            page.wait_for_function("document.querySelector('#agent-prompt').value.length > 100", timeout=5000)
            orig = page.input_value("#agent-prompt")
            page.fill("#agent-prompt", orig + "\n# UI TEST MARKER\n")
            page.click("#agent-save-btn")
            page.wait_for_selector("#agent-save-status:has-text('已保存')", timeout=10000)
            check("后台在线编辑并保存 Agent 提示词", "# UI TEST MARKER" in prompts_copy.read_text(encoding="utf-8"))
            page.screenshot(path=str(tmp / "admin_agents.png"))

            page.click(".tab[data-tab='password']")
            page.fill("#pwd-old", NEW_PASSWORD)
            page.fill("#pwd-new", "Final@9999")
            page.fill("#pwd-confirm", "Final@9999")
            page.click("#pwd-btn")
            page.wait_for_selector("#pwd-status:has-text('已更新')", timeout=10000)
            check("后台修改密码", True)

            page.click("#logout-btn")
            page.wait_for_selector("#login-btn", timeout=10000)
            check("退出回到登录页", page.is_visible("#login-btn"))
            browser.close()

        # 验证真实 YAML 未被改动
        real = (PROJ / "app" / "prompting" / "agent_prompts.yaml").read_text(encoding="utf-8")
        check("真实提示词文件未被测试改动", "# UI TEST MARKER" not in real and "UI Edit" not in real)

        failed = [r for r in results if not r[1]]
        print(("\nADMIN TEST: %d/%d PASS" % (len(results) - len(failed), len(results))), flush=True)
        if failed:
            sys.exit(1)
    finally:
        stop_server(server)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import urllib.error  # noqa: E402

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    import urllib.parse  # noqa: E402

    main()
