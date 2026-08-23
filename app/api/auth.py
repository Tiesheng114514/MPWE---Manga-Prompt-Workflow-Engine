"""用户认证路由：注册（邀请码）、登录、登出、当前用户、免费充值额度领取。

会话用 HttpOnly cookie（mpwe_user，30 天），自动登录，密码不进 cookie。
注册不再做人机验证；人机验证（Turnstile）只在领取「免费充值额度」时使用。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.core import accounts, billing
from app.core.turnstile import TurnstileError, verify_token

COOKIE_NAME = "mpwe_user"


def cookie_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def current_user(request: Request) -> dict:
    """业务路由的登录依赖：未登录抛 401。"""
    user = accounts.session_user(accounts.accounts_db(), cookie_token(request))
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已停用")
    return user


def public_user(user: dict) -> dict:
    return {
        "uid": user["uid"],
        "username": user["username"],
        "invite_code": user["invite_code"],
        "status": user["status"],
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }


def _with_wallets(user: dict) -> dict:
    user = dict(user)
    bdb = billing.billing_db()
    user["wallets"] = billing.get_wallets(bdb, user["uid"])
    user["free_claimed"] = billing.is_free_claimed(bdb, user["uid"])
    return user


def create_auth_router(config: dict) -> APIRouter:
    router = APIRouter()
    db = accounts.accounts_db()

    def _set_session_cookie(response: Response, uid: str) -> None:
        token = accounts.create_session(db, uid)
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=accounts.SESSION_TTL,
        )

    @router.get("/auth/me")
    def me(request: Request) -> dict:
        user = accounts.session_user(db, cookie_token(request))
        if not user:
            raise HTTPException(status_code=401, detail="未登录")
        return {"ok": True, "user": _with_wallets(public_user(user))}

    @router.post("/auth/register")
    def register(request: Request, response: Response, body: dict) -> dict:
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        invite_code = (body.get("invite_code") or "").strip()
        if not invite_code:
            raise HTTPException(status_code=400, detail="注册需要邀请码。")
        try:
            user = accounts.create_user(db, username, password, invite_code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        bdb = billing.billing_db()
        billing.ensure_wallet(bdb, user["uid"])
        # 新用户注册赠送额度（config.yaml -> billing.signup_bonus，可配置）
        bonus = (config.get("billing") or {}).get("signup_bonus") or {}
        try:
            api_bonus = float(bonus.get("api") or 0)
            image_bonus = float(bonus.get("image") or 0)
        except (TypeError, ValueError):
            api_bonus = image_bonus = 0.0
        if api_bonus > 0:
            billing.recharge(bdb, user["uid"], "api", api_bonus, note="新用户注册赠送")
        if image_bonus > 0:
            billing.recharge(bdb, user["uid"], "image", image_bonus, note="新用户注册赠送")
        _set_session_cookie(response, user["uid"])
        return {"ok": True, "user": _with_wallets(public_user(user))}

    @router.post("/auth/free-claim")
    def free_claim(request: Request, body: dict) -> dict:
        """领取免费充值额度（需过 Turnstile 人机验证，每账号限一次）。"""
        user = current_user(request)
        try:
            ok = verify_token(
                config,
                (body.get("turnstile_token") or "").strip(),
                request.client.host if request.client else "",
            )
        except TurnstileError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=400, detail="人机验证未通过，请重试。")
        free = (config.get("billing") or {}).get("free_recharge") or {}
        try:
            api_yuan = float(free.get("api") or 0)
            image_yuan = float(free.get("image") or 0)
        except (TypeError, ValueError):
            api_yuan = image_yuan = 0.0
        try:
            billing.grant_free_recharge(
                billing.billing_db(),
                user["uid"],
                api_yuan,
                image_yuan,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "user": _with_wallets(public_user(user))}

    @router.post("/auth/login")
    def login(request: Request, response: Response, body: dict) -> dict:
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        user = accounts.verify_login(db, username, password)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误，或账号已停用。")
        _set_session_cookie(response, user["uid"])
        return {"ok": True, "user": _with_wallets(public_user(user))}

    @router.post("/auth/logout")
    def logout(request: Request, response: Response) -> dict:
        accounts.delete_session(db, cookie_token(request))
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    return router


__all__ = ["COOKIE_NAME", "create_auth_router", "cookie_token", "current_user"]
