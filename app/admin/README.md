# app/admin —— 管理员后台

管理员后台是**独立服务**（`app/admin_server.py`，端口 8643），
与用户 WebUI（8642）完全分离：只挂管理路由与必要的静态资源，不含任何生图接口。

## 启动方式

```bat
scripts\启动管理员后台WebUI.bat   # 首次运行手动设置管理密码，之后启动/打开后台
scripts\修改管理员密码.bat        # 命令行改密（WebUI 内也可改）
```

## 文件职责

| 文件 | 职责 |
|---|---|
| `admin_server.py`（在 `app/` 下） | 独立 FastAPI 服务入口，挂载 `create_admin_router` + css/js 静态资源 |
| `routes.py` | 页面（`/`、`/login`）与接口（`/api/login|logout|session|overview|password|prompts`） |
| `secrets_store.py` | 隐私数据：固定盐 + PBKDF2-HMAC-SHA256（20 万次迭代），存 `app/隐私数据/secrets.json` |
| `sessions.py` | 内存会话（8 小时），Cookie `mpwe_admin`（HttpOnly、SameSite=Lax） |
| `prompts_api.py` | AI Agent 提示词在线编辑（ruamel 保注释回写 `agent_prompts.yaml`） |
| `launcher.py` | 首次运行设置密码 + 启动/打开管理后台（探测 `/api/session` 避免重复启动） |
| `changepwd.py` | 命令行修改管理密码 |

## 安全要点

- 密码不明文存储：仅存固定盐 + PBKDF2 哈希，校验用常量时间比较；
- 敏感数据目录 `app/隐私数据/` 已被 `.gitignore` 排除，**严禁提交**；
- 登录限流：每 IP 60 秒最多 5 次；Cookie 8 小时过期；
- 接口不返回盐/哈希，日志不打印密码。

## 后端主要接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/login` | 密码登录，下发会话 Cookie |
| POST | `/api/logout` | 注销会话 |
| GET | `/api/session` | 会话状态 |
| GET | `/api/overview` | 概览（后端/ComfyUI/LLM/适配模型） |
| POST | `/api/password` | 修改管理密码 |
| GET/PUT | `/api/prompts[/{id}]` | AI Agent 提示词列表 / 在线编辑 |

## AI Agent 提示词在线编辑的扩展性

- 「AI 提示词 Agent」页的下拉框**自动列出** `app/prompting/agent_prompts.yaml` 里
  全部已配置的 Agent（共用扩写 + 各模型翻译），保存用 ruamel.yaml 保注释回写，
  修改立即生效（无需重启）；
- **给新模型加 Agent**：只需在 YAML 的 `models:` 下新增一段（key = 模型文件名），
  后台自动出现、自动可编辑，无需改 `prompts_api.py`；
- **新增全新 Agent 类型**：在 `prompts_api.py` 的 `_locate()` 增加该类型的 id 定位规则，
  并在 `list_agents()` 里列出，后台即自动适配（编排逻辑见 `app/prompting/agent.py`，
  开发文档见 `app/prompting/README.md`）。

> 用户管理已启用：注册/登录、邀请码、双钱包计费、充值调整、GPU/API 统计，
> 详见 [docs/多用户与任务系统规划.md](../docs/多用户与任务系统规划.md)。
