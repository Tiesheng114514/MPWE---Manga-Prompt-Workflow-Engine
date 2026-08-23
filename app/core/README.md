# app/core —— 任务管理与数据模型

不依赖上层的核心组件。

## jobs.py —— 生成任务管理（JobManager）

- SQLite 持久化登记任务，状态机：`queued → running → done / error / canceled`，
  重启不丢；入队（`enqueue`）/ 领取（`claim`）/ 状态查询全部落库；
- **进度条数据源**：后台轮询线程连接 ComfyUI websocket（`/ws`），
  收取 `progress` 事件（`value/max`）换算成百分比写回任务；
  websocket 不可用时自动退回纯 history 轮询（无百分比，但不影响出图）；
- 任务字段含 `progress`、`stage`（"生成中 X%"），前端每 1.5s 轮询展示；
- 排队中的任务带 `queue_pos`（第 N 位），由队列中更高优先级/更早创建的任务数算出。

## queue.py —— 任务调度器（JobScheduler）

- 后台守护线程：按 优先级 + 创建时间 从 `queued` 队列领取任务；
- 准入两道检查：**每用户并发上限** + **显存预算**（同时运行任务峰值之和 ≤ 容量）；
- 多 ComfyUI 实例分发：每个实例同时只跑 1 个任务，空闲实例轮询分配，
  提交失败的实例临时拉黑并换实例重试（`max_dispatch_attempts` 次后判失败）；
- 服务重启：残留 `running` 任务标记失败、对应 ComfyUI prompt 移出队列，
  `queued` 任务自动重新派发。

## vram.py —— 显存预算（VramBudget）

- 峰值估算：优先 `data/vram_estimates.json` 实测表（按 模型 × 分辨率 取档，
  无精确档按潜空间面积插值/外推），未测模型按 文件大小 × 精度 + 上下文 + 激活 保守估算；
- 容量 = 总显存 − 余量；`fits(reserved, cost)` 决定并行准入；
- 超分（hires）按 2× 尺寸外推峰值，FaceDetailer 附加固定占用。

## schemas.py —— Pydantic 数据模型

| 模型 | 用途 |
|---|---|
| `GenerateRequest` | 文生图/画质增强请求（工作流、模型、提示词、参数、LoRA、Hires/FaceDetailer） |
| `PromptTranslateRequest` | AI 提示词 Agent 翻译请求（text + model） |
| `LoraItem` | 单个 LoRA 的加载配置 |

## 扩展点

- 新增任务类型：在 `jobs.py` 登记、由调度器领取（参照 `_run_polling` 轮询线程）；
- 新增请求模型：在 `schemas.py` 加一个 Pydantic 类，路由直接作为参数注入。
