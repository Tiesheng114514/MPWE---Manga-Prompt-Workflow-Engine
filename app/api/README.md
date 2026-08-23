# app/api —— REST 接口层（用户服务）

用户 WebUI 与后端之间的唯一通信入口。所有路由都在 `routes.py` 的
`create_router(config)` 中定义，由 `main.py` 挂载。

## 前缀约定

- 前端统一走 `/mpwe/*`（绕开广告拦截器对 `/api/` 的过滤规则）；
- `/api/*` 前缀保留兼容旧调用，指向同一批路由。

## 接口分类

| 类别 | 路径 | 说明 |
|---|---|---|
| 基础 | `/mpwe/health`、`/mpwe/config` | 健康检查、运行配置（不含敏感信息） |
| ComfyUI | `/mpwe/comfyui/*` | 状态、模型/采样器/调度器枚举、预设 |
| 生成任务 | `POST /mpwe/generate`、`GET /mpwe/jobs*` | 提交任务、查询状态/进度/图片 |
| 提示词 Agent | `POST /mpwe/prompt/translate`、`GET /mpwe/prompt/jobs*`、`GET /mpwe/prompt/agents` | 大白话翻译任务 |

> 管理员后台接口不在这里：它在独立服务 `app/admin_server.py`（端口 8643）中，
> 路由见 [app/admin/README.md](../admin/README.md)。

## 新增接口

在 `create_router()` 内新增一个 `@router.<method>` 函数即可，例如：

```python
@router.get("/example")
def example() -> dict:
    return {"ok": True}
```

请求/响应模型统一放在 `app/core/schemas.py`（Pydantic）。
