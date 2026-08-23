# app/tests —— 测试脚本

存放本项目自测与真实浏览器点击测试脚本（不放进 `scripts/`，那里只放 `.bat`）。

## 脚本一览

| 脚本 | 类型 | 覆盖内容 |
|---|---|---|
| `selftest_prompt_agent.py` | 离线 | Agent 配置加载、解析、校验、关键道具补插、未适配模型拒绝、未配 Key 报错 |
| `selftest_admin.py` | 离线 | 固定盐幂等、PBKDF2 哈希/校验、会话、Agent 提示词在线编辑（ruamel 保注释回写） |
| `uitest_browser.py` | 浏览器 | 真实点击：Agent 生成、出图进度条、占位符、图片适配、灯箱放大 |
| `uitest_admin.py` | 浏览器 + API | 管理后台：登录/限流/在线编辑提示词/改密/登出 |

## 运行方法

```bat
.venv\Scripts\python.exe app\tests\selftest_prompt_agent.py
.venv\Scripts\python.exe app\tests\selftest_admin.py
.venv\Scripts\python.exe app\tests\uitest_browser.py        # 需要 playwright
.venv\Scripts\python.exe app\tests\uitest_admin.py
```

## 隔离原则（重要）

- 管理员相关测试通过环境变量 `MPWE_PRIVATE_DIR` / `MPWE_PROMPTS_PATH`
  指向**临时目录**，绝不写入真实的 `app/隐私数据/` 与 `agent_prompts.yaml`；
- `uitest_admin.py` 使用临时隐私目录 + 临时提示词副本 + 独立测试端口，
  测试结束时清理，并断言真实文件未被改动；
- 浏览器脚本复用系统 Edge（`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`），
  需先 `pip install playwright`（国内可用清华镜像）。
