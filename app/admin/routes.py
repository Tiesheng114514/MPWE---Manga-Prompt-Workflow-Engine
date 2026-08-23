"""管理员后台路由：登录/登出/会话/概览/改密/AI Agent 提示词在线编辑。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from app.admin import prompts_api, secrets_store, sessions
from app.comfyui.client import ComfyUIClient
from app.core import accounts, billing, gpu_metrics
from app.prompting import loader as prompt_loader

WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"

RATE_LIMIT = 5
RATE_WINDOW = 60

_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def create_admin_router(config: dict) -> APIRouter:
    """创建管理员路由（依赖注入运行配置）。"""
    router = APIRouter()
    client = ComfyUIClient(
        base_url=config["comfyui"]["base_url"],
        timeout=config["comfyui"]["timeout"],
        client_id=config["comfyui"]["client_id"],
    )

    def _cookie_token(request: Request) -> str | None:
        return request.cookies.get("mpwe_admin")

    def _require_session(request: Request) -> str:
        token = _cookie_token(request)
        if not sessions.session_valid(token):
            raise HTTPException(status_code=401, detail="未登录")
        return token or ""

    def _login_limited(ip: str) -> bool:
        now = time.time()
        with _login_lock:
            if len(_login_attempts) > 1000:
                cutoff = now - RATE_WINDOW
                _login_attempts.clear()
            recent = [t for t in _login_attempts.get(ip, []) if now - t < RATE_WINDOW]
            if len(recent) >= RATE_LIMIT:
                _login_attempts[ip] = recent
                return True
            recent.append(now)
            _login_attempts[ip] = recent
            return False

    def _origin_allowed(request: Request) -> bool:
        """跨端口 CSRF 防护：仅允许管理员后台自身来源的变更请求。

        浏览器跨站/跨端口 POST 会带 Origin，非浏览器客户端（curl 等）不带，
        仍由会话 Cookie（SameSite=Strict）兜底。
        """
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        if not origin:
            return True
        port = config.get("admin", {}).get("port", 8643)
        allowed = (
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"http://{config.get('admin', {}).get('host', '127.0.0.1')}:{port}",
        )
        return any(origin.startswith(a) for a in allowed)

    def _guard_mutation(request: Request) -> None:
        if not _origin_allowed(request):
            raise HTTPException(status_code=403, detail="请求来源不被允许")

    # ---------------- 页面 ----------------
    @router.get("/")
    def admin_page(request: Request):
        if not sessions.session_valid(_cookie_token(request)):
            return RedirectResponse("/login", status_code=302)
        return FileResponse(WEBUI_DIR / "admin.html")

    @router.get("/login")
    def admin_login_page(request: Request):
        if sessions.session_valid(_cookie_token(request)):
            return RedirectResponse("/", status_code=302)
        return FileResponse(WEBUI_DIR / "admin_login.html")

    # ---------------- 登录 / 会话 ----------------
    @router.post("/api/login")
    def admin_login(request: Request, response: Response, body: dict):
        _guard_mutation(request)
        ip = request.client.host if request.client else ""
        if _login_limited(ip):
            raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试。")
        password = (body.get("password") or "").strip()
        if not secrets_store.password_set():
            raise HTTPException(
                status_code=403,
                detail="管理密码尚未设置，请先运行 scripts\\启动管理员后台WebUI.bat 完成首次设置。",
            )
        if not secrets_store.verify_password(password):
            raise HTTPException(status_code=401, detail="密码错误")
        token = sessions.create_session()
        response.set_cookie(
            "mpwe_admin",
            token,
            httponly=True,
            samesite="strict",
            path="/",
            max_age=sessions.SESSION_TTL,
        )
        return {"ok": True}

    @router.post("/api/logout")
    def admin_logout(request: Request, response: Response):
        _guard_mutation(request)
        token = _cookie_token(request)
        sessions.invalidate(token)
        response.delete_cookie("mpwe_admin", path="/")
        return {"ok": True}

    @router.get("/api/session")
    def admin_session(request: Request):
        return {"logged_in": sessions.session_valid(_cookie_token(request))}

    @router.get("/api/overview")
    def admin_overview(request: Request):
        _require_session(request)
        llm = config.get("llm") or {}
        bdb = billing.billing_db()
        api_stats = billing.stats_api(bdb)
        image_stats = billing.stats_image(bdb)
        gpu_rows = gpu_metrics.stats_gpu(bdb)
        users = accounts.list_users(accounts.accounts_db())
        invites = accounts.list_invite_codes(accounts.accounts_db())
        try:
            comfy_ok = client.check_connection()
        except Exception:
            comfy_ok = False
        billing_cfg = config.get("billing") or {}
        return {
            "ok": True,
            "version": "0.2.0",
            "comfyui_connected": comfy_ok,
            "llm_configured": bool((llm.get("api_key") or "").strip()),
            "llm_model": llm.get("model", ""),
            "agent_models": prompt_loader.get_supported_agents(),
            "password_set": secrets_store.password_set(),
            "server_time": time.time(),
            "users_count": len(users),
            "invite_codes_count": len(invites),
            "invite_codes_used": sum(int(i.get("used_count") or 0) for i in invites),
            "api_total_mli": sum(int(r["amount_mli"] or 0) for r in api_stats),
            "image_total_mli": sum(int(r["amount_mli"] or 0) for r in image_stats),
            "api_calls": sum(int(r["calls"] or 0) for r in api_stats),
            "api_tokens": sum(int(r["tokens"] or 0) for r in api_stats),
            "image_count": sum(int(r["images"] or 0) for r in image_stats),
            "gpu_total_seconds": round(sum(float(r["gpu_seconds"] or 0) for r in gpu_rows), 1),
            "gpu_total_tflops_hour": round(sum(float(r["tflops_hour"] or 0) for r in gpu_rows), 4),
            "image_price_yuan": float((billing_cfg.get("image") or {}).get("price_per_image", 0.3)),
        }

    # ---------------- 邀请码 ----------------
    @router.get("/api/invite-codes")
    def admin_list_invite_codes(request: Request):
        _require_session(request)
        return {"ok": True, "invite_codes": accounts.list_invite_codes(accounts.accounts_db())}

    @router.post("/api/invite-codes")
    def admin_create_invite_codes(request: Request, body: dict):
        _guard_mutation(request)
        _require_session(request)
        raw_codes = body.get("codes") or []
        max_invites = body.get("max_invites")
        if isinstance(raw_codes, str):
            raw_codes = [line.strip() for line in raw_codes.splitlines() if line.strip()]
        specs = []
        for c in raw_codes:
            code = (c or "").strip()
            if code:
                specs.append((code, max_invites))
        if not specs:
            raise HTTPException(status_code=400, detail="请至少填写一个邀请码。")
        try:
            created = accounts.create_invite_codes(accounts.accounts_db(), specs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "created": created}

    @router.delete("/api/invite-codes/{code}")
    def admin_delete_invite_code(code: str, request: Request):
        _guard_mutation(request)
        _require_session(request)
        try:
            accounts.delete_invite_code(accounts.accounts_db(), code)
        except KeyError:
            raise HTTPException(status_code=404, detail="邀请码不存在")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    # ---------------- 用户管理 ----------------
    def _user_stats(user: dict) -> dict:
        bdb = billing.billing_db()
        uid = user["uid"]
        api_rows = billing.stats_api(bdb)
        img_rows = billing.stats_image(bdb)
        gpu_rows = gpu_metrics.stats_gpu(bdb)
        api = next((r for r in api_rows if r["user_id"] == uid), None)
        img = next((r for r in img_rows if r["user_id"] == uid), None)
        gpu = next((r for r in gpu_rows if r["user_id"] == uid), None)
        public = {
            k: user[k]
            for k in ("uid", "username", "invite_code", "status", "created_at", "last_login_at")
            if k in user
        }
        return {
            **public,
            "wallets": billing.get_wallets(bdb, uid),
            "api": api or {"calls": 0, "tokens": 0, "amount_mli": 0},
            "image": img or {"images": 0, "amount_mli": 0},
            "gpu": gpu or {"jobs": 0, "gpu_seconds": 0.0, "gpu_flops": 0.0, "tflops_hour": 0.0},
        }

    @router.get("/api/users")
    def admin_list_users(request: Request):
        _require_session(request)
        users = accounts.list_users(accounts.accounts_db())
        return {"ok": True, "users": [_user_stats(u) for u in users]}

    @router.get("/api/users/{uid}")
    def admin_user_detail(uid: str, request: Request):
        _require_session(request)
        user = accounts.get_user(accounts.accounts_db(), uid)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        entries = billing.list_entries(billing.billing_db(), uid, limit=200)
        return {"ok": True, "user": _user_stats(user), "entries": entries}

    @router.post("/api/users/{uid}/balance")
    def admin_adjust_balance(uid: str, request: Request, body: dict):
        _guard_mutation(request)
        _require_session(request)
        user = accounts.get_user(accounts.accounts_db(), uid)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        wallet = body.get("wallet") or ""
        try:
            amount = float(body.get("amount") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="金额格式不正确") from None
        try:
            result = billing.recharge(
                billing.billing_db(),
                uid,
                wallet,
                amount,
                note=(body.get("note") or "").strip(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "result": result, "wallets": billing.get_wallets(billing.billing_db(), uid)}

    @router.post("/api/users/{uid}/toggle-active")
    def admin_toggle_user(uid: str, request: Request, body: dict):
        _guard_mutation(request)
        _require_session(request)
        user = accounts.get_user(accounts.accounts_db(), uid)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        status = (body.get("status") or "").strip()
        if not status:
            status = "disabled" if user["status"] == "active" else "active"
        try:
            accounts.set_user_status(accounts.accounts_db(), uid, status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "status": status}

    @router.post("/api/users/{uid}/reset-password")
    def admin_reset_password(uid: str, request: Request, body: dict):
        _guard_mutation(request)
        _require_session(request)
        if accounts.get_user(accounts.accounts_db(), uid) is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        try:
            accounts.reset_password(accounts.accounts_db(), uid, (body.get("new_password") or "").strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    # ---------------- 统计 ----------------
    @router.get("/api/stats/gpu")
    def admin_stats_gpu(request: Request):
        _require_session(request)
        rows = gpu_metrics.stats_gpu(billing.billing_db())
        return {
            "ok": True,
            "rows": rows,
            "total_seconds": round(sum(float(r["gpu_seconds"] or 0) for r in rows), 1),
            "total_tflops_hour": round(sum(float(r["tflops_hour"] or 0) for r in rows), 4),
        }

    @router.get("/api/stats/api")
    def admin_stats_api(request: Request):
        _require_session(request)
        rows = billing.stats_api(billing.billing_db())
        return {
            "ok": True,
            "rows": rows,
            "total_calls": sum(int(r["calls"] or 0) for r in rows),
            "total_tokens": sum(int(r["tokens"] or 0) for r in rows),
            "total_amount_mli": sum(int(r["amount_mli"] or 0) for r in rows),
        }

    @router.post("/api/password")
    def admin_change_password(request: Request, body: dict):
        _guard_mutation(request)
        _require_session(request)
        old = (body.get("old") or "").strip()
        new = (body.get("new") or "").strip()
        if not secrets_store.verify_password(old):
            raise HTTPException(status_code=401, detail="原密码错误")
        if not new or len(new) < 8 or len(new) > 128:
            raise HTTPException(status_code=400, detail="新密码长度须为 8-128 位")
        secrets_store.set_password(new)
        return {"ok": True}

    # ---------------- AI Agent 提示词在线编辑 ----------------
    @router.get("/api/prompts")
    def admin_list_prompts(request: Request):
        _require_session(request)
        try:
            return {"ok": True, "agents": prompts_api.list_agents()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取提示词配置失败: {exc}")

    @router.put("/api/prompts/{agent_id}")
    def admin_update_prompt(agent_id: str, request: Request, body: dict):
        _guard_mutation(request)
        _require_session(request)
        try:
            updated = prompts_api.update_agent(
                agent_id,
                name=body.get("name"),
                description=body.get("description"),
                prompt=body.get("prompt"),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"保存失败: {exc}")
        return {"ok": True, "agent": updated}

    return router
