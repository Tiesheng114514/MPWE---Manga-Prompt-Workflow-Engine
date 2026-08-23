# 模型配置目录

本目录存放每个模型的**官方预设参数**（步数、CFG、采样器、调度器、分辨率、配套 VAE/文本编码器等）。
参数来源为各模型官方仓库/官方工作流文档，用户无需自行输入——WebUI 选好模型后自动套用。

> 注意：这里配置的是**生成参数**，不是提示词。提示词写法指南也在文件里，但不会自动填入输入框。

**取值约定**：官方推荐为区间时，步数取偏高值（例如推荐 20-45 步则填 35），
CFG/采样器取官方推荐值；官方硬性要求（如 NovelAI V2 的 CLIP skip=2）必须写死。

## 文件规范

每个模型一个 YAML 文件，字段如下：

```yaml
name: 模型显示名
model_file: 模型文件名（必须与 models 目录里的完全一致）
category: checkpoints | diffusion_models   # 模型类别
workflow: txt2img | z_image_txt2img | anima_txt2img   # 使用的生成工作流
source: 官方文档/下载地址
params:                 # 自动套用的生成参数
  steps: 20
  cfg: 6.0
  sampler: euler        # ComfyUI 采样器名称
  scheduler: normal     # ComfyUI 调度器名称
  width: 768
  height: 1152
  clip_skip: 0          # CLIP skip（0=不设置；NovelAI V2 等模型必须为 2）
  # diffusion_models 额外字段：
  clip_name: ...        # 文本编码器（官方指定）
  clip_type: ...        # CLIPLoader 类型（官方指定）
  vae_name: ...         # VAE（官方指定）
  model_shift: ...      # ModelSamplingAuraFlow shift
  latent_node: ...      # EmptySD3LatentImage / EmptyLatentImage
prompt:
  style: natural_language | danbooru_tags | tags_and_natural_language
  positive_prefix: ...  # 可选：官方推荐正向前缀
  tag_order: ...        # 可选：官方推荐标签顺序
  guide: 提示词写法说明
negative_default: ...   # 官方推荐负面提示词（仅作参考，不自动填入）

quality:                # 可选：画质增强预设（超分放大重绘 + 脸部修复）
  hires:
    upscale_model: 2x_IllustrationJaNai_V3detail_SPAN_S_40k_fp16.safetensors
    denoise: 0.45       # 重绘降噪强度（0-1，越小越接近放大结果）
    steps: 20           # 重绘步数
    cfg: 5.0            # 重绘 CFG（与模型官方 CFG 保持一致）
  face_detailer:
    detector: bbox/face_yolov8m.pt   # 脸部检测模型（可换 face_yolov8n.pt）
    threshold: 0.5      # 检测置信度阈值
    denoise: 0.35       # 脸部重绘强度
    steps: 16           # 脸部重绘步数
    cfg: 5.0            # 脸部重绘 CFG
    guide_size: 512     # 脸部裁剪引导尺寸
    max_size: 1024      # 脸部最大尺寸

# 预留：LoRA 配置（后续版本启用，按类型自动处理）
# loras:
#   - name: 平滑细节增强                        # 显示名
#     file: SmoothDetailerBooster_v5.safetensors # 文件放在 ComfyUI models/loras/
#     type: quality                             # quality=整体画质提升 / style=风格 / character=角色 / other
#     weight: 0.6                               # 加载权重（多 LoRA 叠加时按官方建议调低）
#     trigger: ""                               # 触发词（如有）
#     cfg: 5                                    # 可选：该 LoRA 推荐 CFG（覆盖模型默认）
#     notes: 官方建议 CFG 3-5，多于 2 个 LoRA 时权重 0.3-0.7
```

## LoRA 叠加（已实现）

每个模型 YAML 的 `loras:` 列表定义推荐 LoRA 与默认开关（`default: true` 自动勾选），
WebUI 的「LoRA 叠加」面板列出 `models/loras` 全部文件，勾选后按顺序加载（LoraLoader 链），
权重可在界面调整。`type` 字段用于区分用途：

- `quality`：整体画质/细节提升，建议始终加载；
- `style`：风格 LoRA，按用户选择加载；
- `hands` / `hair`：手部/发丝修复类；
- `character`：角色 LoRA，与具体角色绑定；
- `nsfw` / `other`：按需求加载。

多 LoRA 叠加时遵循社区规则：超过 2 个 LoRA 权重整体降到 0.3-0.7，避免糊图。

### 手部 / 发丝修复 LoRA（已下载，HF 公共镜像）

| LoRA | 类型 | 默认权重 | 说明 | 状态 |
|---|---|---|---|---|
| Perfect Hands Illustrious | hands | 0.7 | Illustrious 专用手部修复：六指/断指/畸形手掌 | ✅ 已下载 `PerfectHandsIllustrious.safetensors` |
| Detailed Anime Style ILv2 | hair | 0.6 | Illustrious V2 蓬松发丝；官方建议权重 < 0.75 | ✅ 已下载 `Detailed_anime_style-ILv2.safetensors` |
| Hands XL v5.5 | hands | 0.5 | 通用 XL 手部 LoRA（备选，与 Perfect Hands 二选一） | ✅ 已下载 `HandsXL_v55.safetensors` |
| LECO BadHands / GoodHands | hands | +1.0 / -1.0 | 社区组合用法：BadHands 正权重 + GoodHands 负权重 | ✅ 已下载 |

> 提示：负面提示词里建议同时加 `extra fingers, six fingers, bad hands`。

### LoRA 下载来源

- **Civitai**（官方，最全）：模型详情页选 LoRA 分类，搜索 Illustrious/NoobAI 标签；
- **CivArchive**（镜像站，速度快）：`civarchive.com/models/<ID>` 可看镜像与直链；
- **PixAI / SeaArt / Tensor.Art**：搬运站，国内访问快，搜索同名即可；
- **Hugging Face**：部分 LoRA 有 HF 镜像（CivArchive 页面会列出）。
- **xget 加速通道（已实测可用）**：`https://xget.xi-xu.me/civitai/<C站路径>` 或 `https://xget.xi-xu.me/hf/<HF路径>`，
  本机可直连且速度快；但作者设置了"需登录"的模型仍需要 C 站 API 令牌（`?token=...`），加速器无法绕过鉴权。
- **hf-mirror.com**（已实测可用）：HuggingFace 国内镜像，HF 上有的 LoRA 走这个最快。

### One Obsession V14 社区推荐 LoRA（已核实下载来源）

下载时优先选 Civitai 原站；国内访问慢时用 CivArchive 镜像（`civarchive.com/models/<ID>`，页面会列出 CivitAI / HuggingFace 直链），
或 PixAI（`pixai.art` 搜索同名）等搬运站。

#### 1. 整体二次元画质/细节增强（quality，建议始终加载）

| LoRA | 触发词 | 推荐权重 | 官方说明 | 下载 | 状态 |
|---|---|---|---|---|---|
| Smooth Detailer Booster（DigitalPastel，当前 v5） | 无 | 少于 2 个 LoRA：0.7-1.2；多于 2 个 LoRA：0.3-0.7 | 全面改善色彩/光影/阴影/细节；官方建议 CFG 3-5；对 Illustrious 2 系效果更好，任何 XL/Illustrious/NoobAI 底模可用 | https://civitai.com/models/1145743 | ✅ 已下载 `Smooth_Booster_v5.safetensors` |

#### 2. 风格 LoRA（style，按需选 1 个）

| LoRA | 触发词 | 推荐权重 | 官方说明 | 下载 | 状态 |
|---|---|---|---|---|---|
| markinson_solidline（clear line and shiny skin） | markinson_solidline | 0.6-0.8 | 与 solidline 同作者；闪亮皮肤+加粗线条，V-predict LoCon；再叠 solidline 可同时获得低饱和粗线 | https://civitai.com/models/1678365 | ✅ 已下载 `markinson_solidline.safetensors` |
| solidline（clear line with low saturation） | solidline | 0.6-0.8 | LoCon（LyCORIS），V-predict；**专门基于 Obsession（Illustrious-XL）训练**，与本模型最配；线条干净、低饱和 | https://civitai.com/models/1463869 | ⏳ C 站独家，需手动下载 |
| CloBA Style Illustrious | CloBAstyle | 0.6-0.8 | 作者明确推荐搭配 OneObsession 使用（任何 Illustrious 系也可用）；华丽时装插画风格 | https://civitai.com/models/2433462 | ⏳ C 站/PixAI 独家，需手动下载 |

#### 2.5 NSFW 增强 LoRA（nsfw，按需求加载）

| LoRA | 触发词 | 推荐权重 | 官方说明 | 下载 | 状态 |
|---|---|---|---|---|---|
| N/SFW Filter / Slider（IllustriousXL） | 无 | 0.3-1.0（正向=更 NSFW） | 滑杆类 LoRA，正权重提升 NSFW 表现力，负权重走纯情向；几乎兼容所有风格/角色/写实模型 | https://civitai.com/models/909623 | ✅ 已下载 `NSFWFilter_illusXL_Incrs_v1.safetensors` |
| Detailer NoobAI（NSFW 细节增强，替代 Zoda） | 无 | 0.4-0.7 | 增强 NSFW 场景细节与纹理；NoobAI/Illustrious 通用 | HF 镜像（Bryan32/IllustriousPonyXL_Loras） | ✅ 已下载 `Detailer_NoobAI_Incrs_v1.safetensors` |
| Random NSFW Poses v9（Illustrious XL） | 无 | 0.5-0.8 | NSFW 姿势库，配合提示词出指定姿势 | HF 镜像（highscoregames12018/lora-collection） | ✅ 已下载 `random-nsfw-poses-v9-illustriousxl-lora-nochekaiser.safetensors` |
| Zoda – NSFW Detailer v3 | 无 | 0.5-0.8 | 专门增强 NSFW 场景的细节与表情表现 | https://civitai.com/models/1879987 | ❌ C 站锁登录，全网无网盘/镜像，已用 Detailer NoobAI 替代 |
| PornMaster-noobXL & Illustrious | 无 | 0.8-1.2 | 提升提示词准确度、细节、色彩鲜艳度与美感（NSFW 向） | https://civarchive.com/seaart/models/d2ip3t5e878c73d9dj30/versions/cd83e86185864b70b9e523767dfc47dd | ❌ C 站锁登录，暂无网盘分享 |
| NSFW Lora For Illustrious（TestV1） | 无 | 0.8-1.2 | 定向 NSFW 强化：姿态/视角/镜头语言优化 | https://tensor.art/models/997402303528982879 | ❌ Tensor.Art 独家，暂无网盘分享 |

> 已全网核实（B 站/贴吧/网盘搜索引擎/资源站）：solidline、CloBA、Zoda、PornMaster 等 C 站锁登录文件**没有公开网盘分享**，
> 如后续有人搬运会补进来；当前用同类型公开镜像替代。

#### 3. 角色 LoRA（character，按具体角色选）

- **灵魂潮汐（Soul Tide）角色 LoRA 合集**（Hugging Face：`kongbai-84/soultide_lora`）：基于 One Obsession 训练，作者推荐权重 0.65，含多角色、多角度一致性；适合做固定角色。
- **立华奏 / Tachibana Kanade LHZ-v2.0**（https://civitai.com/models/2120962）：作者注明底模就是 oneObsession，用本模型最匹配。
- 其他角色：在 Civitai / PixAI 按「角色名 + Illustrious 或 NoobAI」搜索，优先找简介里写了「trained on OneObsession / Obsession」的，匹配度最高。

#### 4. 其他（other，可选）

- 风格类也可以换成更通用的**画师风格 LoRA**（如 Watanabe Akio 渡边明夫 10-in-1，https://civitai.com/models/1761757），按画师串出不同画风。
- 想要更锐利的细节还可以试 **BSS Detail Enhancer Slider**（https://civitai.com/models/1850267，XL/IL/PN 通用）。

#### 叠加建议（当前阶段）

默认推荐「1 quality + 1 style + 1 character」最多叠 3 个；NSFW 场景把 character 换成 nsfw 滑杆：

1. Smooth Detailer Booster：权重 0.5 左右，CFG 保持模型预设（建议 3-5 区间）；
2. markinson_solidline（或 solidline / CloBA Style 之一）：权重 0.7 左右，必须写对应触发词；
3. 角色 LoRA 权重 0.65 左右（必须写角色触发词），或 NSFW 滑杆权重 0.3-0.5。

叠 3 个以上时所有 LoRA 权重整体降到 0.3-0.7，避免过拟合糊图。

> 这些权重/CFG 规则后续会按 LoRA 的 `type` 写进自动配置逻辑（quality 恒加载、style 按用户选择、character 与角色绑定），
> 配置文件结构已在下方预留，具体数值后续按实测效果微调。

## 新增模型步骤

1. 把模型文件放入对应目录（`D:\Comfy-Desktop\ComfyUI-Shared\models\...`）；
2. 在本目录新建 `模型名.yaml`，按上面规范填写（参数以官方文档为准）；
3. 重启 WebUI 后端即可自动识别。

## 当前模型

| 模型 | 类别 | 工作流 | 官方参数来源 |
|---|---|---|---|
| Z-Image Turbo | diffusion_models | z_image_txt2img | Tongyi-MAI/Z-Image-Turbo |
| Z-Anime Distill 8-Step | diffusion_models | z_image_txt2img | SeeSee21/Z-Anime |
| Anima Aesthetic v1.1 | diffusion_models | anima_txt2img | circlestone-labs/Anima |
| ItN's Comic Merge | checkpoints | txt2img | 本地工作流 |
| One Obsession V14 | checkpoints | txt2img | Civitai 1318945 |
| Animagine XL 4.0 Opt Clear | checkpoints | txt2img | easygoing0114/animagine-xl-4.0-opt_clear |
| Animagine XL 4.0 Opt INT8 | checkpoints | txt2img | easygoing0114/animagine-xl-4.0-opt_clear |
| ChenkinNoob XL V0.5 | checkpoints | txt2img | Civitai 2167995 |
| Illustrious XL v2.0 | checkpoints | txt2img | OnomaAIResearch/Illustrious-XL-v2.0 |
| NovelAI Diffusion Anime V2 | checkpoints | txt2img | NovelAI/nai-anime-v2 |
