# app/comfyui —— ComfyUI 对接

负责与本地 ComfyUI Server API（默认 `http://127.0.0.1:8188`）通信，
并把模型预设、工作流图等业务逻辑集中在这里。

## 文件职责

| 文件 | 职责 |
|---|---|
| `client.py` | ComfyUI REST 客户端：健康检查、模型枚举、提交任务（`/prompt`）、轮询历史（`/history`）、下载图片（`/view`）、取消/中断等 |
| `presets.py` | 读取 `model_configs/*.yaml` 并扁平化为前端/工作流可用的预设（Checkpoint 与扩散模型分开） |
| `workflows/` | 工作流图构建器（API 格式），见其子目录 README |

## 常用能力

- 模型枚举：`list_models("checkpoints" / "diffusion_models" / "loras" / ...)`
  从 `/object_info` 解析可选值；
- 参数预设：`get_checkpoint_preset(name)` / `get_diffusion_preset(name)`，
  按 `model_configs/` 里的 YAML 返回官方推荐参数；
- 提交出图：`client.queue_prompt(workflow)` → `wait_for_prompt`/`get_prompt_output_images`。

## 扩展点

- 新增 ComfyUI 接口调用：在 `client.py` 加一个方法（`self._get/_post` 已有封装）；
- 新增模型：只需在 `model_configs/` 加 YAML，无需改代码。
