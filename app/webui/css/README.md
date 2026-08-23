# app/webui/css —— 样式

- `style.css`：全站唯一样式文件，含用户页与管理后台两套界面；
- 使用 CSS 变量（颜色、圆角、边框），深色主题；
- 包含：顶部导航（管理后台）、进度条、灯箱、Agent 区块、响应式卡片等；
- 全局 `[hidden] { display: none !important; }` 保证 `hidden` 属性不被其他 display 规则覆盖。
