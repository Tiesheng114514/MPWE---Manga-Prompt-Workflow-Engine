# app/webui/js/features —— 用户页子模块

| 文件 | 职责 |
|---|---|
| `quality.js` | 画质增强面板：Hires 超分重绘 + FaceDetailer 脸部修复的参数收集 |
| `loras.js` | LoRA 叠加面板：列出模型目录下的 LoRA、勾选与权重调整 |

这两个模块由 `app.js` 在初始化时引入（`index.html` 中的 script 标签顺序在 app.js 之前）。
