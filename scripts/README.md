# scripts 脚本目录

本目录存放项目全部 `.bat` 脚本。以后新增脚本（管理员提权、备份、清理、模型管理、部署等）统一放这里。

> 面向普通使用者的两个入口脚本放在**项目根目录**（不在本目录）：
> `安装向导.bat`（首次安装：装依赖 / 定位或下载 ComfyUI / 配置模型与工作流路径）与
> `一键启动.bat`（一次拉起全部服务，窗口内 `q` 退出、`l` 看 WebUI 日志）。

## 编码约定（重要）

- `.bat` 文件支持两种编码，二选一：
  1. **纯 ASCII**（英文，最稳妥）；
  2. **GBK/ANSI 中文**（Windows 中文系统默认代码页 936）。
- **禁止使用 UTF-8 编码的 `.bat`**（无论是否带 BOM）：cmd.exe 按系统代码页解析文件，
  UTF-8 的中文字节会被读成乱码，导致命令无法识别或直接报错。
- 全角符号、emoji 不要写进 `.bat`。
- 当前已有脚本（`install_deps.bat`、`start_comfyui.bat`、`start_webui.bat`）已使用 GBK 中文提示。
- 本 README 及项目内 `.md` 文件用 UTF-8 没有问题（Markdown 由编辑器读取），
  只有 `.bat` 需要遵守上述编码约定。

## 路径约定

- 所有脚本第一行固定 `cd /d "%~dp0.."`：把工作目录切到项目根目录（`scripts` 的上一级）。
- 脚本内一律使用相对项目根的相对路径，例如 `.venv\Scripts\python.exe`。

## 现有脚本

| 脚本 | 用途 | 是否需要管理员 |
|---|---|---|
| `install_deps.bat` | 安装/更新 Python 依赖到 `.venv` | 否 |
| `start_comfyui.bat` | 无界面启动 ComfyUI 后端服务（默认端口 8188；支持多实例） | 否 |
| `start_webui.bat` | 启动我们的 WebUI（前端 + 后端服务）并自动打开浏览器（端口 8642） | 否 |
| `结束所有任务.bat` | 一键关闭本项目启动的 WebUI 与 ComfyUI 服务进程 | 否 |
| `启动管理员后台WebUI.bat` | 首次运行设置管理密码并打开管理员后台（独立端口 8643） | 否 |

## 路径配置（安装向导生成）

`安装向导.bat` 运行后会生成 `data\local_paths.bat`（已被 .gitignore 排除），
其中保存本机的 ComfyUI 目录 / Python / 模型目录 / 工作流目录。
`start_comfyui.bat` 启动时会优先读取它；没有该文件时使用内置默认路径。
| `修改管理员密码.bat` | 命令行修改管理员密码 | 否 |

> 测试脚本（`selftest_*` / `uitest_*` / `test_queue.py`）统一放在 `app/tests/`；
> 本目录另有少量开发辅助 `.py` 脚本：

| Python 脚本 | 用途 |
|---|---|
| `measure_vram.py` | 实测每个模型各分辨率档的峰值显存，写入 `data/vram_estimates.json`（跑之前确认 ComfyUI 空闲） |
| `smoke_server.py` | 启动后端 + 验证健康检查/队列接口后自动关闭（临时 DB，不影响线上数据） |

## 关于窗口与服务状态

- `start_comfyui.bat` / `start_webui.bat` 会打开**可见的控制台窗口**（标题带服务名），
  关闭对应窗口即可停止该服务；窗口内容即为运行日志。
- 如果服务进程脱离窗口在后台运行（例如之前用隐藏方式启动过），
  双击 `结束所有任务.bat` 一键全部关闭，再重新用启动脚本拉起。

## 启动顺序（前后端分离）

先启动 ComfyUI（后端绘图引擎），再启动我们的 WebUI（前端）：

```bat
start_comfyui.bat
start_webui.bat
```

`start_comfyui.bat` 说明：

- 直接用 ComfyUI 自带的 `standalone-env\python.exe` 启动 `main.py`（无桌面界面）；
- 模型路径通过项目根目录 `comfyui_extra_model_paths.yaml` 映射到 `D:\Comfy-Desktop\ComfyUI-Shared`；
- 每个实例使用独立数据库（`data\comfyui_端口.db`）；
- 默认启动 1 个实例（127.0.0.1:8188）。如需多实例并行，设置环境变量
  `MPWE_COMFYUI_WORKERS=2`（2~4）再运行，端口依次为 8188、8189...；
- 关闭对应的 `ComfyUI-xx` 最小化窗口即可停止该实例。

## 新增脚本模板

```bat
@echo off
setlocal
cd /d "%~dp0.."

REM 在这里写逻辑（GBK 编码，支持中文）

pause
```

需要管理员权限的脚本：右键 -> 以管理员身份运行；或在脚本开头加提权检测（后续需要时再补充）。
