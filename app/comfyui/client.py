"""ComfyUI Server API 客户端。

所有对 ComfyUI 的 HTTP 调用都封装成独立方法（函数），
后续新增功能时在对应区域添加方法即可，保持可扩展性。
"""

from __future__ import annotations

import time
from typing import Any

import requests

# 模型类别 -> (加载节点类型, 字段名)，用于从 /object_info 提取可选模型
_MODEL_FIELDS: dict[str, tuple[str, str]] = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "loras": ("LoraLoader", "lora_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "vae": ("VAELoader", "vae_name"),
    "diffusion_models": ("UNETLoader", "unet_name"),
    "clip": ("CLIPLoader", "clip_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "clip_vision": ("CLIPVisionLoader", "clip_name"),
    "upscale_models": ("UpscaleModelLoader", "model_name"),
}


class ComfyUIError(RuntimeError):
    """ComfyUI 通信或执行错误。"""


class ComfyUIClient:
    """封装 ComfyUI Server API 的轻量客户端。"""

    def __init__(self, base_url: str, timeout: int = 30, client_id: str = "mpwe-webui") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = client_id

    # ---------------- 基础 HTTP 封装 ----------------
    def _get(self, path: str, params: dict | None = None, timeout: int | None = None) -> requests.Response:
        try:
            resp = requests.get(f"{self.base_url}{path}", params=params, timeout=timeout or self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ComfyUIError(f"ComfyUI GET {path} 失败: {exc}") from exc
        return resp

    def _post(self, path: str, json_body: dict | None = None, timeout: int | None = None) -> requests.Response:
        try:
            resp = requests.post(f"{self.base_url}{path}", json=json_body, timeout=timeout or self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ComfyUIError(f"ComfyUI POST {path} 失败: {exc}") from exc
        return resp

    # ---------------- 连接与状态 ----------------
    def check_connection(self) -> bool:
        """快速探测 ComfyUI 是否在线。"""
        try:
            self._get("/system_stats", timeout=5)
            return True
        except ComfyUIError:
            return False

    def get_system_stats(self) -> dict:
        """获取 ComfyUI 系统信息（设备、显存、Python 版本等）。"""
        return self._get("/system_stats").json()

    def get_queue(self) -> dict:
        """获取当前队列。"""
        return self._get("/queue").json()

    def get_object_info(self) -> dict:
        """获取全部节点定义（用于枚举模型、采样器等选项）。"""
        return self._get("/object_info").json()

    def get_history(self, prompt_id: str | None = None) -> dict:
        """获取执行历史；传 prompt_id 时只查该任务。"""
        path = f"/history/{prompt_id}" if prompt_id else "/history"
        return self._get(path).json()

    # ---------------- 工作流提交 ----------------
    def queue_prompt(self, workflow: dict, extra_data: dict | None = None) -> str:
        """提交工作流图（API 格式），返回 prompt_id。"""
        payload: dict[str, Any] = {"prompt": workflow, "client_id": self.client_id}
        if extra_data:
            payload["extra_data"] = extra_data
        data = self._post("/prompt", json_body=payload).json()
        if "prompt_id" not in data:
            raise ComfyUIError(f"ComfyUI 未返回 prompt_id: {data}")
        return data["prompt_id"]

    def cancel_prompt(self, prompt_id: str) -> None:
        """从队列中删除指定任务。"""
        self._post("/queue", json_body={"delete": [prompt_id]})

    def interrupt(self) -> None:
        """中断当前正在执行的任务。"""
        self._post("/interrupt")

    # ---------------- 结果获取 ----------------
    def get_prompt_output_images(self, prompt_id: str) -> list[dict]:
        """从 history 中提取某个任务的输出图片信息列表。"""
        history = self.get_history(prompt_id)
        entry = history.get(prompt_id)
        if not entry:
            return []
        images: list[dict] = []
        for output in (entry.get("outputs") or {}).values():
            for image in output.get("images") or []:
                images.append(
                    {
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    }
                )
        return images

    def wait_for_prompt(self, prompt_id: str, timeout: int = 300, interval: float = 1.0) -> dict:
        """轮询 /history 直到任务完成/出错/超时，返回 history 条目。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("completed") or status.get("status_str") == "completed":
                    return entry
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI 执行出错: {status.get('messages', [])}")
            time.sleep(interval)
        raise ComfyUIError(f"等待 ComfyUI 任务超时（{timeout}s）: {prompt_id}")

    def get_image(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        """通过 /view 下载图片内容。"""
        return self._get("/view", params={"filename": filename, "subfolder": subfolder, "type": image_type}).content

    def upload_image(self, image_bytes: bytes, filename: str, subfolder: str = "", image_type: str = "input") -> dict:
        """上传图片到 ComfyUI（默认 input 目录），返回 ComfyUI 的上传结果。"""
        files = {"image": (filename, image_bytes, "image/png")}
        data: dict[str, str] = {"overwrite": "true", "type": image_type}
        if subfolder:
            data["subfolder"] = subfolder
        try:
            resp = requests.post(f"{self.base_url}/upload/image", files=files, data=data, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ComfyUIError(f"ComfyUI 上传图片失败: {exc}") from exc
        return resp.json()

    # ---------------- 模型与参数枚举 ----------------
    def list_models(self, category: str = "checkpoints") -> list[str]:
        """列出某类模型文件（从 /object_info 的选项里解析）。"""
        mapping = _MODEL_FIELDS.get(category)
        if not mapping:
            raise ComfyUIError(f"不支持的模型类别: {category}（可用: {', '.join(_MODEL_FIELDS)}）")
        node_type, field = mapping
        return self._list_choice(node_type, field)

    def list_samplers(self) -> list[str]:
        """列出 KSampler 支持的采样器。"""
        return self._list_choice("KSampler", "sampler_name")

    def list_schedulers(self) -> list[str]:
        """列出 KSampler 支持的调度器。"""
        return self._list_choice("KSampler", "scheduler")

    def list_clip_types(self) -> list[str]:
        """列出 CLIPLoader 支持的文本编码器类型。"""
        return self._list_choice("CLIPLoader", "type")

    def _list_choice(self, node_type: str, field: str) -> list[str]:
        """从节点定义中提取某个下拉字段的可选值。"""
        info = self.get_object_info()
        node = info.get(node_type)
        if not node:
            return []
        required = node.get("input", {}).get("required", {})
        field_info = required.get(field)
        if not field_info:
            return []
        raw = field_info[0]
        if isinstance(raw, list):
            return list(raw)
        # 新版 ComfyUI 紧凑格式：["COMBO", {"options": "a b c"}]
        if raw == "COMBO" and isinstance(field_info[1], dict):
            opts = field_info[1].get("options")
            if isinstance(opts, list):
                return list(opts)
            if isinstance(opts, str):
                return opts.split()
        return []
