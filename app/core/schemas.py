"""API 请求/响应数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoraItem(BaseModel):
    """单个 LoRA 的加载配置。"""

    file: str = Field("", description="LoRA 文件名（models/loras 下）")
    weight: float = Field(0.6, description="加载权重（多 LoRA 叠加时建议 0.3-0.7）")


class PromptTranslateRequest(BaseModel):
    """AI 提示词 Agent 翻译请求。"""

    text: str = Field("", description="用户的大白话画面描述")
    model: str = Field("", description="当前选中模型的 model_file（如 one obsession_v14.safetensors）")


class GenerateRequest(BaseModel):
    """生成请求：对应一个工作流构建函数的所有参数。"""

    workflow: str = "txt2img"
    checkpoint: str = Field("", description="Checkpoint 模型文件名（txt2img 使用）")
    # 扩散模型（UNET + CLIP + VAE）专用参数
    unet_name: str | None = Field(None, description="扩散模型文件名（diffusion_models）")
    clip_name: str | None = Field(None, description="文本编码器文件名（text_encoders）")
    clip_type: str | None = Field(None, description="CLIPLoader 类型，留空则按官方预设自动选择")
    vae_name: str | None = Field(None, description="VAE 文件名")
    model_shift: float | None = Field(None, description="AuraFlow shift，留空则按官方预设自动选择")
    clip_skip: int = Field(0, description="CLIP skip（如 NovelAI V2 必须为 2；0 表示不设置）")
    prompt: str = ""
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 6.0
    sampler: str = "euler"
    scheduler: str = "normal"
    seed: int = -1
    batch_size: int = 1
    filename_prefix: str = "MPWE"
    # ---------------- 画质增强（超分放大重绘 + 脸部修复） ----------------
    hires_fix: bool = Field(False, description="是否启用超分放大重绘（Hires fix）")
    upscale_model: str = Field("", description="超分模型文件名（UpscaleModelLoader）")
    hires_denoise: float = Field(0.45, description="超分重绘阶段的降噪强度（0-1）")
    hires_steps: int = Field(0, description="超分重绘步数（0=沿用主生成步数）")
    hires_cfg: float = Field(0.0, description="超分重绘 CFG（0=沿用主生成 CFG）")
    face_detailer: bool = Field(False, description="是否启用脸部修复（FaceDetailer）")
    face_detector: str = Field("bbox/face_yolov8m.pt", description="脸部检测模型（UltralyticsDetectorProvider）")
    face_threshold: float = Field(0.5, description="脸部检测置信度阈值")
    face_denoise: float = Field(0.35, description="脸部修复重绘强度")
    face_steps: int = Field(16, description="脸部修复步数")
    face_cfg: float = Field(5.0, description="脸部修复 CFG")
    face_guide_size: float = Field(512, description="脸部修复引导尺寸")
    face_max_size: float = Field(1024, description="脸部修复最大尺寸")
    # ---------------- LoRA 叠加 ----------------
    loras: list[LoraItem] = Field(default_factory=list, description="叠加的 LoRA 列表（按顺序加载）")
    # ---------------- 二次创作（quality_pass） ----------------
    image_filename: str = Field("", description="二次创作的输入图片文件名（生成结果）")
    image_subfolder: str = Field("", description="输入图片子目录")
    image_type: str = Field("output", description="输入图片所在类型（output/input/temp）")
