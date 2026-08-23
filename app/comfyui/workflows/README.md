# app/comfyui/workflows —— 工作流图构建器

把"逻辑参数"（提示词、尺寸、步数、模型名、LoRA……）拼成 ComfyUI 的
API 格式工作流图（JSON）。采用**注册制**，新增功能无需改动现有代码。

## 文件职责

| 文件 | 职责 |
|---|---|
| `registry.py` | 注册表：`register()` 装饰器 + `list_workflows()` / `build_workflow()` |
| `txt2img.py` | Checkpoint 模型文生图（SD/SDXL/Illustrious 系） |
| `diffusion.py` | 扩散模型文生图（Z-Image / Anima 系，含 UNET+CLIP+VAE） |
| `quality.py` | 画质增强（Hires 超分重绘） |
| `quality_pass.py` | 二次创作入口（对已生成图做画质增强） |
| `loras.py` | LoRA 叠加链（按顺序串 LoraLoader） |

## 新增一个工作流

```python
@register("my_workflow")          # 功能名，前端 workflow 字段传这个
def build_my_workflow(**params) -> dict:
    """返回 ComfyUI API 格式的工作流图。"""
    return {...}
```

注册后 `GET /mpwe/comfyui/workflows` 会自动列出。
