# app/prompting —— AI 提示词 Agent

把用户的大白话自动翻译成所选模型专用的完整英文提示词（正向 + 负向）。
核心原则：**程序与模型无关，特调全部数据化在 YAML 配置里**。

## 两阶段流水线

1. **扩写 Agent（所有模型共用）**：大白话 → 600-700 字中文「画面需求书」；
2. **翻译 Agent（按模型特调）**：需求书 → 全英文 `POSITIVE:` / `NEGATIVE:` 提示词。

## 文件职责

| 文件 | 职责 |
|---|---|
| `agent_prompts.yaml` | **所有 Agent 的系统提示词配置**（可在线编辑，保存即生效） |
| `loader.py` | 读取/校验配置，按 mtime 自动热重载；`get_supported_agents()` 返回“模型→Agent”清单 |
| `llm.py` | OpenAI 兼容 LLM 客户端（默认 DeepSeek `deepseek-v4-flash`），超时/错误分类 |
| `agent.py` | 两阶段编排、解析、校验重试、关键道具补插、长度预算裁剪 |
| `jobs.py` | 翻译任务的内存管理 + 后台线程（进度回传） |

## 当前已配置的 Agent（10 个模型 + 1 个共用扩写）

| Agent id | 作用域 | 说明 |
|---|---|---|
| `expand_agent` | 共用（所有模型） | 大白话 → 中文画面需求书，所有模型一致 |
| `translate_agent:<model_file>` | 每模型一个 | 画面需求书 → 该模型特调的英文 POSITIVE/NEGATIVE |

已配置专属翻译 Agent 的模型（key 与 `model_configs/*.yaml` 的 `model_file` 一一对应）：

| model_file（Agent 的 key） | Agent 名称 | 提示词风格 |
|---|---|---|
| `one obsession_v14.safetensors` | One Obsession V14 Prompt Engineer | Danbooru 标签 + 官方质量前缀 + 风格开关 |
| `z_image_turbo_fp8.safetensors` | Z-Image Turbo Prompt Engineer | 纯自然语言长句；**官方明确无负面提示词**，只输出 POSITIVE |
| `z-anime-distill-8step-fp8.safetensors` | Z-Anime Distill 8-Step Prompt Engineer | 纯自然语言长句；8 步蒸馏下负面词**效果有限**（官方），保持简短 |
| `anima-aesthetic-v1.1.safetensors` | Anima Aesthetic v1.1 Prompt Engineer | 标签 + 自然语言混用，官方 `score_7, safe` 前缀 + 官方标签顺序 |
| `animagine-xl-4.0-opt_clear.safetensors` | Animagine XL 4.0 Prompt Engineer | 官方质量词 `masterpiece, high score, great score, absurdres` + 官方负面模板 |
| `animagine-xl-4.0-opt_INT8_ConvRot_HQ.safetensors` | Animagine XL 4.0 INT8 Prompt Engineer | 同 4.0（INT8 量化版，词表更精简） |
| `ChenkinNoob-XL-V0.5.safetensors` | ChenkinNoob XL V0.5 Prompt Engineer | 官方正面 `masterpiece, best quality, newest, high resolution, aesthetic, excellent, year 2026` |
| `Illustrious-XL-v2.0.safetensors` | Illustrious XL v2.0 Prompt Engineer | Danbooru 标签；`masterpiece, best quality, amazing quality` 前置 + `very aesthetic, newest` |
| `ItNsComicMerge.safetensors` | ItN's Comic Merge Prompt Engineer | Danbooru 标签（SD1.5，77 token 预算）；作者提示：背景/服装从简 |
| `NovelAI Diffusion Anime V2.safetensors` | NovelAI Diffusion Anime V2 Prompt Engineer | 纯 Danbooru 标签（CLIP skip 2）；V2 已移除 `masterpiece`，用 `best quality, amazing quality` |

> 以上特调提示词均依据各模型官方文档 / 官方页面与社区提示词指南重写
> （Z-Image/Z-Anime 官方页、Anima 官方 README、Animagine XL 4.0 官方 README、
> ChenkinNoob Civitai 页、Illustrious XL v2.0 官方用户指南、ItN's Comic Merge
> 作者说明、NovelAI 官方文档），并附来源要点写在每个 `prompt:` 内。

## 配置结构（agent_prompts.yaml）

```yaml
expand_agent:                    # 共用扩写 Agent
  name: ...
  prompt: |
    # 全英文系统提示词

models:
  "<model_file>.safetensors":    # 每模型专属翻译 Agent，key 为模型文件名
    translate_agent:
      name: ...
      description: ...
      prompt: |
        ...
      validation:                # 校验参数（标签/词数预算、必需质量词等）
        ...
```

## 严格一对一（不混用）

- 翻译 Agent 只在 `models:` 里配置过的模型上可用；**没有通用回退**；
- 未配置的模型：后端拒绝翻译请求、前端禁用按钮；
- 一个模型文件只能有一个 `translate_agent`，特调提示词永远不会被混用到别的模型上。

## 如何新增 / 扩展 Agent（开发文档）

### 场景一：改现有 Agent 的提示词（零代码，后台点两下）

1. 启动管理后台（`scripts\启动管理员后台WebUI.bat`，端口 8643）；
2. 进入「AI 提示词 Agent」页，下拉框选择目标 Agent（共用扩写 / 某模型翻译 Agent）；
3. 修改 `name / description / prompt` 后保存，**立即生效，无需重启服务**；
4. 也可以直接编辑 `app/prompting/agent_prompts.yaml`，效果相同（后台编辑走
   ruamel.yaml，会保留注释与格式）。

### 场景二：给新模型加专属翻译 Agent（只改配置，不用改代码）

1. 先把模型接入：在 `model_configs/` 新增模型 YAML（规范见
   `model_configs/README.md`），记录它的 `model_file`（必须与 ComfyUI 里实际文件名一致）；
2. 打开 `app/prompting/agent_prompts.yaml`，在 `models:` 下复制一段已有条目；
3. 把 key 改成与 `model_file` **完全相同**（区分大小写，含空格）；
4. 参考该模型官方文档 / 社区提示词指南，把 `prompt:` 重写成该模型特调的全英文系统提示词：
   - 自然语言系（Z-Image / Z-Anime）：要求长句描述、主体优先、明确光照；
   - 标签系（NoobAI / Illustrious / NovelAI / SD1.5）：要求 Danbooru 标签 + 官方质量词；
   - 混用系（Anima / Animagine）：标签为主 + 短自然语言短语，官方前缀/顺序优先；
5. 按需调整 `validation:`（预算与必需质量词，见下表）；
   - 自然语言系记得加 `natural_language: true`（关键道具会插到第一句之后，不破坏主体前置）；
   - 不支持/不依赖负面词的模型（如 Z-Image）设 `negative_required: false`；
6. 保存即生效：用户端下拉框选中该模型后「AI 生成提示词」按钮自动点亮，
   管理后台下拉框自动出现该 Agent——**前后端不需要改任何代码**。

### 场景三：新增一种全新类型的 Agent（需要改代码）

如果“翻译”之外还要新增 Agent 大类（例如“画质评估 Agent”“扩写风格 A/B 对比”等）：

1. `agent_prompts.yaml`：新增顶层分组（如 `evaluate_agent:`），把提示词放进去；
2. `app/prompting/loader.py`：新增对应的读取方法（仿照 `get_expand_agent()`）；
3. `app/admin/prompts_api.py`：在 `_locate()` 增加该类型的 id 定位规则，
   在 `list_agents()` 里把它列出来——**管理后台会自动出现并支持在线编辑**；
4. `app/prompting/agent.py`：编排新的调用链（如扩写 → 翻译 → 画质评估）；
5. 前端 `app/webui/js/app.js` 在需要的位置接入该能力；
6. 在 `README.md`（本文件）的“当前已配置的 Agent”表里补一行。

## 校验参数说明（validation）

| 字段 | 含义 |
|---|---|
| `min_tags` / `max_tags` | POSITIVE 按逗号切分的段数预算 |
| `min_words` / `max_words` | POSITIVE 英文词数预算 |
| `negative_required` | 是否强制要求 NEGATIVE 行（SD 系必须 true） |
| `natural_language` | 是否自然语言模型（true 时关键道具补插到第一句之后） |
| `required_tags` | 必须出现的质量词（不区分大小写），如 `masterpiece` |

生成后会做硬性验收：纯英文、质量词前缀、关键道具补插（需求书点名的伞/路灯/雨等必须出现）、
长度预算裁剪；连续失败自动带原因重试 ≤2 次。

## LLM 配置

- 默认模型：`deepseek-v4-flash`（DeepSeek V4 Flash 官方 API 名称，
  旧的 `deepseek-chat` 已于 2026-07-24 停用）；
- 配置文件：`config.yaml` 的 `llm:` 段 + 项目根目录 `.env`（参考 `.env.example`）；
- 环境变量覆盖：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MPWE_LLM_MODEL`、`MPWE_LLM_TIMEOUT`。

## 在线编辑

管理员后台（独立服务 8643）的「AI 提示词 Agent」页可直接修改这些提示词，
写入使用 ruamel.yaml **保留注释与格式**；保存后运行时自动重载，无需重启。
