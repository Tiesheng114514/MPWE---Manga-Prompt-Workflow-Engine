"""GPU 算力估算与统计。

单位说明（行业常用口径）：
  - FLOPs            ：总浮点运算量（工作量）
  - TFLOPS            ：10^12 次浮点运算/秒（速率）
  - TFLOPS·时         ：TFLOPS × 小时（工作量，= FLOPs / 1e12 / 3600）
  - GPU 秒            ：GPU 实际占用时长（用任务起止时间记录）

这里对每次生成按 步数 × 潜空间 token × 模型系数 估算 FLOPs（粗估，用于横向比较），
并记录真实 GPU 耗时（秒）。两个值都入库，后台分开展示。
"""

from __future__ import annotations

from typing import Any

# 粗略模型系数（FLOP/step/token）：按典型 1024x1536 + 超分 + 脸部修复任务
# 校准到 ~0.4 TFLOPS·时/张（4060m 实跑 2-3 分钟量级），用于横向比较而非精确计量。
MODEL_FACTOR = 1.2e8
LATENT_CHANNELS = 4
FACE_REGION_LATENT_TOKENS = 64 * 64  # 脸部修复区域粗估


def estimate_flops(params: dict[str, Any] | None) -> float:
    """按生成参数估算总 FLOPs（主生成 + 超分重绘 + 脸部修复）。"""
    params = params or {}
    steps = max(1, int(params.get("steps") or 20))
    width = max(64, int(params.get("width") or 1024))
    height = max(64, int(params.get("height") or 1024))
    batch = max(1, int(params.get("batch_size") or 1))

    def latent_tokens(w: int, h: int) -> int:
        return max(1, w // 8) * max(1, h // 8) * LATENT_CHANNELS

    main_flops = steps * latent_tokens(width, height) * MODEL_FACTOR * batch
    total = float(main_flops)

    if bool(params.get("hires_fix")):
        hires_steps = max(1, int(params.get("hires_steps") or steps))
        total += hires_steps * latent_tokens(width * 2, height * 2) * MODEL_FACTOR
    if bool(params.get("face_detailer")):
        face_steps = max(1, int(params.get("face_steps") or 16))
        total += face_steps * FACE_REGION_LATENT_TOKENS * MODEL_FACTOR
    return total


def flops_to_tflops_hour(flops: float) -> float:
    return flops / 1e12 / 3600.0


def format_tflops_hour(value: float) -> str:
    """把 TFLOPS·时 转成可读文本（自动换单位）。"""
    if value >= 1:
        return f"{value:.3f} TFLOPS·时"
    if value >= 1e-3:
        return f"{value * 1e3:.3f} GFLOPS·时"
    return f"{value * 1e6:.1f} MFLOPS·时"


def format_flops(value: float) -> str:
    if value >= 1e18:
        return f"{value / 1e18:.3f} EFLOPs"
    if value >= 1e15:
        return f"{value / 1e15:.3f} PFLOPs"
    if value >= 1e12:
        return f"{value / 1e12:.3f} TFLOPs"
    return f"{value:.3e} FLOPs"


def stats_gpu(db) -> list[dict]:
    """按用户聚合 GPU 算力：任务数、GPU 秒、估算 FLOPs / TFLOPS·时。"""
    with db.conn() as conn:
        rows = conn.execute(
            "SELECT user_id, COUNT(*) AS jobs, "
            "SUM(COALESCE(gpu_seconds, 0)) AS gpu_seconds, "
            "SUM(COALESCE(gpu_flops_estimate, 0)) AS gpu_flops "
            "FROM jobs WHERE status = 'done' GROUP BY user_id ORDER BY gpu_flops DESC"
        ).fetchall()
        return [
            {
                "user_id": r["user_id"],
                "jobs": int(r["jobs"] or 0),
                "gpu_seconds": round(float(r["gpu_seconds"] or 0), 1),
                "gpu_flops": float(r["gpu_flops"] or 0),
                "tflops_hour": flops_to_tflops_hour(float(r["gpu_flops"] or 0)),
            }
            for r in rows
        ]


__all__ = [
    "estimate_flops",
    "flops_to_tflops_hour",
    "format_flops",
    "format_tflops_hour",
    "stats_gpu",
]
