"""双钱包计费：API 钱包（DeepSeek 真金白银）+ 图片钱包（本地 GPU）。

金额统一用「厘」（0.001 元）整数存储，避免浮点误差。
billing_entries 是一张总台账，用 kind 区分：
  - api / image          ：消费（amount_mli 为负）
  - api_recharge / image_recharge ：后台充值/调整（可为正或负，但不允许余额变负）
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from app.core.db import Database, init_mpwe_db, mpwe_db_path, row_to_dict, rows_to_dicts

_init_lock = threading.Lock()
_db: Database | None = None


def billing_db() -> Database:
    global _db
    with _init_lock:
        if _db is None:
            _db = init_mpwe_db()
        return _db


def ensure_wallet(db: Database, uid: str) -> dict:
    with db.conn() as conn:
        conn.execute("INSERT OR IGNORE INTO wallets (user_id) VALUES (?)", (uid,))
        return row_to_dict(
            conn.execute(
                "SELECT api_balance_mli, image_balance_mli FROM wallets WHERE user_id = ?",
                (uid,),
            ).fetchone()
        )  # type: ignore[return-value]


def get_wallets(db: Database, uid: str) -> dict:
    wallet = ensure_wallet(db, uid)
    return {
        "api_balance_mli": int(wallet["api_balance_mli"] or 0),
        "image_balance_mli": int(wallet["image_balance_mli"] or 0),
    }


def _wallet_col(kind: str) -> str:
    """账单 kind → 钱包余额列。"""
    if kind in ("api", "api_recharge"):
        return "api_balance_mli"
    if kind in ("image", "image_recharge"):
        return "image_balance_mli"
    raise ValueError(f"未知账单类型: {kind}")


def _adjust(db: Database, uid: str, kind: str, amount_mli: int, ref_type: str, ref_id: str, detail: dict) -> dict:
    """同一连接内调整余额并记账，返回新余额。"""
    col = _wallet_col(kind)
    with db.conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO wallets (user_id) VALUES (?)", (uid,))
        row = conn.execute(
            f"SELECT {col} AS b FROM wallets WHERE user_id = ?", (uid,)
        ).fetchone()
        new_balance = int(row["b"] or 0) + amount_mli
        if new_balance < 0:
            raise ValueError("余额不足")
        conn.execute(
            f"UPDATE wallets SET {col} = ? WHERE user_id = ?", (new_balance, uid)
        )
        conn.execute(
            "INSERT INTO billing_entries (user_id, kind, amount_mli, balance_after_mli, ref_type, ref_id, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uid,
                kind,
                amount_mli,
                new_balance,
                ref_type,
                ref_id,
                json.dumps(detail, ensure_ascii=False),
                time.time(),
            ),
        )
    return {"balance_mli": new_balance, "amount_mli": amount_mli}


def recharge(db: Database, uid: str, wallet: str, amount_yuan: float, note: str = "") -> dict:
    """后台充值/调整余额。wallet: api / image。amount_yuan 可为负（扣回），但不允许余额变负。"""
    if wallet not in ("api", "image"):
        raise ValueError("钱包只能是 api 或 image")
    mli = round(float(amount_yuan) * 1000)
    if mli == 0:
        raise ValueError("金额不能为 0")
    return _adjust(
        db,
        uid,
        f"{wallet}_recharge",
        mli,
        "manual",
        "",
        {"note": note or "", "operator": "admin"},
    )


def is_free_claimed(db: Database, uid: str) -> bool:
    """免费充值额度是否已领取（每账号限一次）。"""
    with db.conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM billing_entries WHERE user_id = ? AND kind = 'free_recharge' LIMIT 1",
            (uid,),
        ).fetchone()
        return row is not None


def grant_free_recharge(db: Database, uid: str, api_yuan: float, image_yuan: float) -> dict:
    """免费充值额度：给两个钱包各入账并记一次性标记。"""
    if is_free_claimed(db, uid):
        raise ValueError("免费充值额度已领取")
    note = "免费充值额度（人机验证）"
    result: dict = {}
    if api_yuan > 0:
        result["api"] = recharge(db, uid, "api", api_yuan, note=note)
    if image_yuan > 0:
        result["image"] = recharge(db, uid, "image", image_yuan, note=note)
    with db.conn() as conn:
        wallet = get_wallets(db, uid)
        conn.execute(
            "INSERT INTO billing_entries (user_id, kind, amount_mli, balance_after_mli, ref_type, ref_id, detail, created_at) "
            "VALUES (?, 'free_recharge', 0, ?, 'manual', '', ?, ?)",
            (
                uid,
                wallet.get("image_balance_mli", 0),
                json.dumps(
                    {"api_yuan": api_yuan, "image_yuan": image_yuan, "note": note},
                    ensure_ascii=False,
                ),
                time.time(),
            ),
        )
    return result


def charge_api(db: Database, uid: str, usage: dict, price_info: dict, ref_id: str = "") -> int:
    """按一次 LLM 调用实时扣 API 钱包，返回本次消费（厘）。余额不足抛 ValueError。"""
    cost_mli = calc_api_cost_mli(price_info, usage)
    if cost_mli <= 0:
        return 0
    _adjust(
        db,
        uid,
        "api",
        -cost_mli,
        "prompt_job",
        ref_id,
        {
            "model": price_info.get("model", ""),
            "peak": bool(price_info.get("peak")),
            "input_cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens") or 0),
            "input_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "amount_yuan": round(cost_mli / 1000.0, 6),
        },
    )
    return cost_mli


def charge_images(db: Database, uid: str, count: int, price_per_image_yuan: float, ref_id: str = "") -> int:
    """任务出图后按张数扣图片钱包。余额不足时扣到 0 并记 note（已在提交前预检）。"""
    if count <= 0:
        return 0
    cost_mli = round(float(price_per_image_yuan) * 1000) * int(count)
    try:
        _adjust(
            db,
            uid,
            "image",
            -cost_mli,
            "job",
            ref_id,
            {
                "image_count": int(count),
                "price_per_image_yuan": float(price_per_image_yuan),
                "amount_yuan": round(cost_mli / 1000.0, 4),
            },
        )
    except ValueError:
        # 极端情况：余额不够本次张数，扣到 0
        wallet = get_wallets(db, uid)
        bal = int(wallet["image_balance_mli"])
        if bal > 0:
            _adjust(
                db,
                uid,
                "image",
                -bal,
                "job",
                ref_id,
                {
                    "image_count": int(count),
                    "price_per_image_yuan": float(price_per_image_yuan),
                    "amount_yuan": round(bal / 1000.0, 4),
                    "note": "余额不足，按剩余余额扣除",
                },
            )
        return bal
    return cost_mli


# ---------------- API 定价（DeepSeek V4 Flash 官方峰谷价） ----------------


def is_peak_hour(now: datetime | None = None, peak_hours=None) -> bool:
    now = now or datetime.now()
    peak_hours = peak_hours or [[9, 12], [14, 18]]
    hm = now.hour * 60 + now.minute
    for start, end in peak_hours:
        if start * 60 <= hm < end * 60:
            return True
    return False


def calc_api_cost_mli(price_info: dict, usage: dict) -> int:
    """按官方单价（元/百万 tokens）计算一次调用的费用（厘）。"""
    prices = price_info.get("prices") or {}
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = usage.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = int(usage.get("prompt_tokens") or 0) - hit
    out = int(usage.get("completion_tokens") or 0)
    yuan = (
        hit / 1e6 * float(prices.get("input_cache_hit") or 0)
        + miss / 1e6 * float(prices.get("input_cache_miss") or 0)
        + out / 1e6 * float(prices.get("output") or 0)
    )
    return int(round(yuan * 1000))


def api_price_info(config: dict, now: datetime | None = None) -> dict:
    """按当前时段返回计价信息（供计费与展示）。"""
    billing = config.get("billing") or {}
    api = billing.get("api") or {}
    peak = is_peak_hour(now, api.get("peak_hours"))
    prices = api.get("peak") if peak else api.get("off_peak")
    return {
        "model": api.get("model") or "",
        "peak": peak,
        "prices": prices or {},
    }


def list_entries(db: Database, uid: str, limit: int = 100) -> list[dict]:
    with db.conn() as conn:
        return rows_to_dicts(
            conn.execute(
                "SELECT * FROM billing_entries WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        )


def stats_api(db: Database) -> list[dict]:
    """按用户聚合 API 消耗：请求数、总 token、金额（厘）。"""
    with db.conn() as conn:
        rows = conn.execute(
            "SELECT user_id, COUNT(*) AS calls, "
            "SUM(CAST(json_extract(detail, '$.total_tokens') AS INTEGER)) AS tokens, "
            "SUM(-amount_mli) AS amount_mli "
            "FROM billing_entries WHERE kind = 'api' GROUP BY user_id ORDER BY amount_mli DESC"
        ).fetchall()
        return [
            {
                "user_id": r["user_id"],
                "calls": int(r["calls"] or 0),
                "tokens": int(r["tokens"] or 0),
                "amount_mli": int(r["amount_mli"] or 0),
            }
            for r in rows
        ]


def stats_image(db: Database) -> list[dict]:
    """按用户聚合图片计费：张数、金额（厘）。"""
    with db.conn() as conn:
        rows = conn.execute(
            "SELECT user_id, "
            "SUM(CAST(json_extract(detail, '$.image_count') AS INTEGER)) AS images, "
            "SUM(-amount_mli) AS amount_mli "
            "FROM billing_entries WHERE kind = 'image' GROUP BY user_id ORDER BY amount_mli DESC"
        ).fetchall()
        return [
            {
                "user_id": r["user_id"],
                "images": int(r["images"] or 0),
                "amount_mli": int(r["amount_mli"] or 0),
            }
            for r in rows
        ]


__all__ = [
    "api_price_info",
    "billing_db",
    "calc_api_cost_mli",
    "charge_api",
    "charge_images",
    "ensure_wallet",
    "get_wallets",
    "is_peak_hour",
    "list_entries",
    "recharge",
    "stats_api",
    "stats_image",
]
