# app —— 应用代码（后端 + 前端）

本目录是整个 MPWE 的应用代码：Python 后端（FastAPI）+ 浏览器端 WebUI（原生 HTML/CSS/JS）。

## 两个服务入口

| 文件 | 服务 | 端口 | 说明 |
|---|---|---|---|
| `main.py` | 用户 WebUI（文生图等业务） | 8642 | 业务接口 `/mpwe/*` + 用户页静态资源 |
| `admin_server.py` | 管理员后台（独立服务） | 8643 | 只挂管理路由 `/login`、`/api/*`，与用户服务完全分离 |

启动方式（推荐用 `scripts/` 下的 bat）：

- `scripts\start_webui.bat` → `python -m app.main`
- `scripts\启动管理员后台WebUI.bat` → 首次设置管理密码后 `python -m app.admin_server`

## 目录职责

| 目录 | 职责 |
|---|---|
| `api/` | REST 接口层（用户服务的唯一通信入口） |
| `core/` | 任务管理（JobManager + 进度）与 Pydantic 数据模型 |
| `comfyui/` | ComfyUI Server API 客户端 + 工作流图构建器 |
| `prompting/` | AI 提示词 Agent（两阶段流水线，配置驱动） |
| `admin/` | 管理员后台：密码/会话/隐私数据/Agent 提示词在线编辑 |
| `webui/` | 前端页面、样式与脚本（用户页 + 管理后台页共用） |
| `tests/` | 自测与浏览器点击测试脚本 |
| `隐私数据/` | 敏感数据（固定盐、管理员密码哈希），**已被 .gitignore 排除** |

## 配置加载

`config.py` 负责加载 `config.yaml` + 环境变量（`.env`）：服务端口、管理员端口、
ComfyUI 地址、LLM（DeepSeek）配置等。新增配置项先在这里加默认值与环境变量覆盖。

详细功能说明见项目根 [README.md](../README.md) 与 [docs/功能文档.md](../docs/功能文档.md)。
