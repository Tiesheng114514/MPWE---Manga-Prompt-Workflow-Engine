"""工作流构建器包（按功能拆分）。

目录约定：
  registry.py    注册表（register / list / build）
  txt2img.py     文生图（Checkpoint 模型）
  diffusion.py   扩散模型文生图（Z-Image / Anima）
  quality.py     画质增强（超分放大重绘 + 脸部修复）
  loras.py       LoRA 叠加链
  quality_pass.py 二次创作（对已生成图片做画质增强）

新增功能时：新建一个功能模块，用 @register("功能名") 注册，
然后在下方 import 该模块即可自动被发现。
"""

from .registry import build_workflow, list_workflows, register

# 导入各功能模块以触发注册
from . import diffusion, quality_pass, txt2img  # noqa: E402,F401

__all__ = ["build_workflow", "list_workflows", "register"]
