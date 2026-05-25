# UI 样式优化测试计划

## 测试目标

验证 `Execution log` 下方 artifact 信息布局的样式优化没有破坏现有 UI 服务、任务详情数据加载、runtime log 展示入口和 artifact Markdown 预览入口，并通过人工检查确认视觉层级和响应式表现达标。

## 自动化测试

### 必跑测试

- 命令：`python -m pytest tests/test_ui_api.py`
- 目的：确认 UI API、静态资源服务、任务详情 view-model、runtime/test log 相关基础行为仍通过。
- 证据：记录 pytest 通过结果；如果实现新增前端静态测试，应同时记录新增测试结果。

### 建议新增或补充

- 若实现修改 `index.html` 结构，补充测试确认静态 HTML 中仍存在 `data-tab="execlog"`、`#iterationBar`、`#runtimeContent`、`.execlog-artifacts`、`#artifactList`。
- 若实现修改 `renderArtifacts()`，补充测试或轻量脚本验证 Markdown artifact 仍按 phase 分组，非 Markdown artifact 可见性策略不被意外改变。
- 若实现只改 CSS，可不新增复杂 DOM 测试，但必须保留必跑测试证据。

## 人工验证

### 桌面视口

1. 启动本地 UI：`python -m agentloop ui --host 127.0.0.1 --port 8765`。
2. 打开 `http://127.0.0.1:8765`。
3. 选择任务 `20260525-102722-ui`。
4. 点击 `Execution log` tab。
5. 检查 runtime 区域下方 `Artifacts all phases` 是否有明确区域边界、标题层级、分组结构和可读 preview。

需要记录的证据：桌面截图或人工检查说明，包含 artifact 区域。

### 窄屏视口

1. 将浏览器宽度调整到 `900px` 以下，或使用浏览器设备模式。
2. 保持同一任务和 `Execution log` tab。
3. 检查 artifact header、文件名、meta、Markdown preview 不重叠，区域滚动可用。

需要记录的证据：窄屏截图或人工检查说明。

## 代码评审门禁

评审者在批准实现前应确认：

- 变更范围符合方案，只涉及 `agentloop/ui_static/index.html`、`agentloop/ui_static/app.js`、`agentloop/ui_static/styles.css` 和必要测试。
- 未引入新前端依赖、构建步骤、外部字体或图标库。
- 未修改任务执行、runtime summary、artifact API 数据语义。
- 未回滚或覆盖工作区中与本任务无关的既有改动。
- `acceptance.json` 中所有 required 项都有对应证据或明确待补证据。

## 退出条件

只有在自动化测试通过、桌面与窄屏人工检查完成、评审者确认没有范围外代码变更后，才可认为后续实现满足本测试计划。
