# UI 样式优化方案

## 推荐方案

建议将 `Execution log` 下方的 `.execlog-artifacts` 从一个松散列表升级为明确的信息区域：保留现有静态页面、原生 JavaScript 和 `styles.css` 架构，只在 `agentloop/ui_static/index.html`、`agentloop/ui_static/app.js`、`agentloop/ui_static/styles.css` 内做小范围调整。

核心方向是把 `Artifacts all phases` 做成“阶段产物工作区”，强调信息层级、扫描效率和与 runtime 区域的视觉连续性，而不是做成装饰性卡片堆叠。实现上建议包含以下变化：

- 为 `.execlog-artifacts` 增加独立区域容器、标题栏和简短 meta，使用户能明确理解 runtime log 下方展示的是跨阶段产物。
- 将 artifact phase group 做成更清晰的分段结构，强化 `Framing`、`Research`、`Design`、`Reviews`、`Final` 的阶段关系。
- 优化 artifact item 的头部信息密度：文件名、大小、截断提示和更新时间应更容易扫描，避免与 Markdown preview 混在一起。
- 收敛嵌套滚动风险：Markdown preview 保留可控高度，但区域间距、边界和滚动层级需要更清楚。
- 保持当前浅色工作台风格，使用已有 CSS variables、现有圆角和阴影尺度，避免引入新的 UI 库、字体、图标库或复杂视觉资源。
- 在 `max-width: 900px` 下保持单列阅读体验，artifact header 和 meta 不应挤压或重叠。

推荐视觉基调是“安静、密集、工程化的任务产物面板”：低对比背景分区、清晰边框、紧凑标题、有限强调色。该方向适合 AgentLoop 这类工作台 UI，能提升可读性而不改变业务语义。

## 实现边界

本阶段不执行实现。后续获批后，建议优先修改：

- `agentloop/ui_static/index.html`：必要时为 artifact 区域补充 header/meta 容器。
- `agentloop/ui_static/app.js`：必要时为 artifact group/item 增加语义化 class、状态文本或计数信息。
- `agentloop/ui_static/styles.css`：主要样式落点，覆盖 artifact 区域、group、item、Markdown preview 和响应式规则。
- `tests/test_ui_api.py` 或新增轻量前端静态测试：验证静态资源/API 仍可访问，必要时验证关键选择器存在。

不建议修改 `agentloop/api.py` 的 artifact 数据语义，除非实现阶段确认 UI 必须展示非 Markdown artifact。当前请求是样式优化，不应扩大为数据模型改造。

## 备选方案

### 方案 A：仅调整 CSS

只修改 `.execlog-artifacts`、`.artifact-list`、`.artifact-group`、`.artifact-item` 和 `.markdown-body` 的样式，不改 HTML 和 JavaScript。

优点是风险最低、回归面小。缺点是标题栏、阶段摘要、空状态或额外 meta 的表达能力有限，难以显著改善信息层级。

### 方案 B：完整重构 artifact 渲染

重写 `renderArtifacts()`，支持 Markdown、JSON、review 文件和更多状态展示。

优点是信息完整性更好。缺点是超出“UI 样式优化”的初始范围，会触及 artifact 数据筛选、内容渲染和测试覆盖，审批前不建议采用。

### 方案 C：引入 UI 组件库或图标库

使用现成组件重做 artifact 面板。

优点是组件一致性可能更高。缺点是当前 UI 是静态页面加原生 JavaScript，引入依赖会增加构建和维护成本，不符合本次小范围优化目标。

## 风险

- 当前 artifact 列表只渲染 `.md` 文件，样式优化可能暴露“JSON 产物不可见”的产品问题，但不应在本任务中默认解决。
- runtime 区域最小高度为 `560px`，artifact 区域位于其后；如果只优化 artifact 样式，用户仍可能需要较多滚动才能看到下方信息。
- `.markdown-body` 与外层 tab panel 存在嵌套滚动，调整高度或边距时需要避免移动端体验退化。
- 现有测试不覆盖前端 DOM/CSS 视觉结果，后续实现需要至少补充一个自动化验证，防止关键区域丢失或静态资源破坏。
- 工作区已有非本任务产生的修改和 `__pycache__` 变更，后续实现时需要避免回滚无关改动。

## 推荐评审门禁

实现前应确认：优化目标仍限定为 `Execution log` 下方 artifact 信息布局；不改变 runtime log 业务逻辑；不引入新依赖；至少提供静态/API 自动化测试证据和人工截图或浏览器检查证据。
