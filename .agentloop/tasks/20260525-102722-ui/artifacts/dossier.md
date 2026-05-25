# UI 样式优化现状调查 Dossier

## 1. Current-State Archive

### 任务范围

- 已批准的问题框定将目标限定为 `execution log` 下方的信息布局，成功输出被定义为后续阶段可用的 UI 设计方案或视觉风格建议；本调查阶段不提出方案、不修改应用代码。来源：`.agentloop/tasks/20260525-102722-ui/artifacts/framing.md`。
- 当前任务状态为 `INVESTIGATING`，`current_phase` 为 `investigation`，调查产物路径为 `.agentloop/tasks/20260525-102722-ui/artifacts/dossier.md`。来源：`.agentloop/tasks/20260525-102722-ui/state.json`。

### UI 页面结构

- 本地 UI 是静态页面加原生 JavaScript：`index.html` 引入 `/styles.css` 和 `/app.js`，没有前端构建管线。见 `agentloop/ui_static/index.html:7`、`agentloop/ui_static/index.html:219`。
- 主体布局由 `.shell` 包含左侧 `.sidebar` 与右侧 `.main`，右侧详情区域是 `.detail-panel`。见 `agentloop/ui_static/index.html:10`、`agentloop/ui_static/index.html:39`、`agentloop/ui_static/styles.css:131`、`agentloop/ui_static/styles.css:331`。
- 详情页有两个 tab：`Basic` 和 `Execution log`。`Execution log` 的按钮使用 `data-tab="execlog"`，副标题是 `iterations & artifacts`。见 `agentloop/ui_static/index.html:58` 到 `agentloop/ui_static/index.html:61`。
- `Execution log` tab 内部顺序是：`#iterationBar`、`.runtime-layout`、`.execlog-artifacts`。`.execlog-artifacts` 标题为 `Artifacts all phases`，下方容器为 `#artifactList`。见 `agentloop/ui_static/index.html:84` 到 `agentloop/ui_static/index.html:93`。

### Runtime Log 区域现状

- `renderRuntime(detail)` 从 `detail.runtime` 读取 `by_iteration` 和 `latest_iteration`。如果没有 `by_iteration`，但存在旧形态的 `agents` 或 `tests`，会构造一个兼容的单 iteration 列表。见 `agentloop/ui_static/app.js:1178` 到 `agentloop/ui_static/app.js:1189`。
- `#iterationBar`、`#runtimeTabs`、`#runtimeContent` 每次渲染都会清空后重建。见 `agentloop/ui_static/app.js:1190` 到 `agentloop/ui_static/app.js:1195`。
- 如果没有 runtime 输出，`#runtimeContent` 显示 `No runtime output yet.`。见 `agentloop/ui_static/app.js:1197` 到 `agentloop/ui_static/app.js:1199`。
- iteration chip 显示 `Iteration {idx + 1}`、agent/test 数量、通过/失败测试计数，并给最新 iteration 添加 `is-latest`。见 `agentloop/ui_static/app.js:1205` 到 `agentloop/ui_static/app.js:1219`。
- runtime 左侧条目把当前 iteration 的 agents 和 tests 合并为一个列表；每个条目展示状态点、label、`Iteration {currentDisplayNum}` 和 `agent`/`test` 类型。见 `agentloop/ui_static/app.js:1222` 到 `agentloop/ui_static/app.js:1243`。
- test 详情内容包含 meta、`command`、`log` 三部分；agent 详情内容包含 meta、`stdout`、`stderr` 三部分。见 `agentloop/ui_static/app.js:1245` 到 `agentloop/ui_static/app.js:1258`。
- runtime 布局目前是两列 grid：左列固定 `220px`，右列自适应，最小高度 `560px`。见 `agentloop/ui_static/styles.css:951` 到 `agentloop/ui_static/styles.css:958`。
- runtime tabs 是白底、有边框、圆角和阴影的纵向列表，最大高度 `560px`，溢出滚动。见 `agentloop/ui_static/styles.css:959` 到 `agentloop/ui_static/styles.css:972`。
- runtime 内容卡片是白底、有边框、`var(--radius-lg)` 圆角、`18px 20px` padding 和轻阴影。见 `agentloop/ui_static/styles.css:1075` 到 `agentloop/ui_static/styles.css:1082`。
- 日志块、命令块和 copy block 共用样式：浅灰背景、浅边框、`pre-wrap`、monospace、`12.5px` 字号。日志块最大高度为 `460px`。见 `agentloop/ui_static/styles.css:581` 到 `agentloop/ui_static/styles.css:597`。

### Execution Log 下方信息区现状

- 目标区域在 DOM 中对应 `.execlog-artifacts`，位于 runtime log 区域之后，标题为 `Artifacts all phases`，内容容器为 `#artifactList`。见 `agentloop/ui_static/index.html:90` 到 `agentloop/ui_static/index.html:93`。
- `.execlog-artifacts` 当前只有 `margin-top: 24px`，没有独立卡片边框、背景、标题栏或密度控制。见 `agentloop/ui_static/styles.css:1665`。
- `renderArtifacts(detail)` 清空 `#artifactList`，然后只展示 `detail.artifacts` 中 `.md` 后缀的 artifact；非 Markdown artifact 不进入当前列表。见 `agentloop/ui_static/app.js:843` 到 `agentloop/ui_static/app.js:849`。
- artifact 按 `artifactPhase(name)` 分组。当前映射为：`framing.*` 到 `Framing`，`dossier.md` 到 `Research`，`proposal.md`、`acceptance.*`、`test-plan.md` 到 `Design`，`review-*.json` 到 `Reviews`，`final-report.md` 到 `Final`，其他为 `Other`。见 `agentloop/ui_static/app.js:831` 到 `agentloop/ui_static/app.js:839`。
- 分组展示顺序固定为 `Framing`、`Research`、`Design`、`Reviews`、`Final`、`Other`。见 `agentloop/ui_static/app.js:841`。
- 每个 artifact group 使用 `<section class="artifact-group">`，标题行是 `.artifact-group-head`，显示 phase 名称和文件数量。见 `agentloop/ui_static/app.js:857` 到 `agentloop/ui_static/app.js:865`。
- 每个 artifact item 使用 `<section class="artifact-item">`，头部显示文件名、大小和 truncation 信息，正文使用 `.markdown-body` 渲染 preview。见 `agentloop/ui_static/app.js:866` 到 `agentloop/ui_static/app.js:879`。
- artifact list 是 grid，间距 `12px`；artifact group 是 grid，间距 `8px`；artifact item 是白底、有边框、`var(--radius-lg)` 圆角、`16px 18px` padding 和轻阴影。见 `agentloop/ui_static/styles.css:869` 到 `agentloop/ui_static/styles.css:890`。
- artifact header 是两列 grid：文件名自适应，meta 自动宽度；文件名使用 monospace、`12.5px`，单行省略。见 `agentloop/ui_static/styles.css:891` 到 `agentloop/ui_static/styles.css:912`。
- Markdown preview 有最大高度 `480px`、内部滚动、上边框、`14px` 顶部 padding，正文行高 `1.65`。见 `agentloop/ui_static/styles.css:1438` 到 `agentloop/ui_static/styles.css:1450`。

### 数据与 API 来源

- 静态资源由 `AgentLoopUIHandler._serve_static()` 从 `agentloop/ui_static` 目录读取；`/` 会映射到 `index.html`。见 `agentloop/ui.py:18`、`agentloop/ui.py:141` 到 `agentloop/ui.py:158`。
- `GET /api/tasks/{task_id}` 返回 `build_task_detail()`，其中包含 `artifacts`、`runtime`、`execution_approval`、`human_review` 等 view-model。见 `agentloop/ui.py:73` 到 `agentloop/ui.py:79`、`agentloop/api.py:598` 到 `agentloop/api.py:647`。
- artifact 数据由 `list_task_artifacts()` 从 `.agentloop/tasks/<task_id>/artifacts` 读取，按文件名排序，并为每个文件提供 `name`、`path`、`size`、`updated_at`、`preview`。见 `agentloop/api.py:343` 到 `agentloop/api.py:358`。
- runtime summary 由 `latest_runtime_summary()` 构造，包含 `iterations`、`latest_iteration`、latest `agents`/`tests` 和 `by_iteration`。见 `agentloop/api.py:534` 到 `agentloop/api.py:595`。
- CLI 通过 `python -m agentloop ui --host 127.0.0.1 --port 8765` 启动本地 UI，默认 host 为 `127.0.0.1`，默认 port 为 `8765`。见 `agentloop/cli.py:138` 到 `agentloop/cli.py:141`、`agentloop/cli.py:747` 到 `agentloop/cli.py:751`。

### 当前视觉基调

- 全局主题变量以浅色工作台为主：`--bg #f7f8fa`、`--panel #ffffff`、`--accent #5b5bf0`，字体变量为 `Inter` 优先的 sans 和 `JetBrains Mono` 优先的 mono。见 `agentloop/ui_static/styles.css:1` 到 `agentloop/ui_static/styles.css:37`。
- 基础按钮使用浅边框、`var(--radius-sm)`、`13px` 字号、`white-space: nowrap`、ellipsis。见 `agentloop/ui_static/styles.css:56` 到 `agentloop/ui_static/styles.css:79`。
- tab panel 使用 `overflow: auto` 和统一 padding；活跃面板用 `display: block`。见 `agentloop/ui_static/styles.css:561` 到 `agentloop/ui_static/styles.css:562`。
- 响应式规则在 `max-width: 900px` 时将 `.runtime-layout` 改为单列，并调整详情 header、tab panel padding 和 settings 等布局。见 `agentloop/ui_static/styles.css:1424` 到 `agentloop/ui_static/styles.css:1436`。

## 2. Baseline Data Or Reproduction

### 可复现步骤

1. 在仓库根目录运行：`python -m agentloop ui --host 127.0.0.1 --port 8765`。
2. 打开 `http://127.0.0.1:8765`。
3. 选择任务 `20260525-102722-ui`。
4. 点击 `Execution log` tab。
5. 观察页面顺序：顶部为 iteration chip，随后是 runtime tabs + runtime content，两者下方是 `Artifacts all phases` 区域。

### 当前任务实例基线

- 当前任务 `20260525-102722-ui` 的状态是 `INVESTIGATING`，phase 是 `investigation`。
- 当前 artifact 目录只包含 `framing.json` 和 `framing.md`，文件大小分别为 `2696` bytes 和 `2682` bytes。
- API view-model 中 `detail.artifacts` 返回 2 个 artifact，但前端 `renderArtifacts()` 只展示 `.md`，因此当前 `Artifacts all phases` 只会展示 `framing.md`，分组为 `Framing`。
- 当前 `runtime.latest_iteration` 为 `0`，`runtime.by_iteration` 有 1 项：iteration `0`，`agent_count=2`，`test_count=0`，`tests_passed=0`，`tests_failed=0`。
- 当前 runtime entries 是两个 `framer` agent，runtime 均为 `codex`，exit code 均为 `0`，stdout/stderr 均有日志内容。
- 当前没有 test log entries。
- 当前 workspace 中 `build_task_list()` 返回 4 个任务。

### 测试与覆盖基线

- `tests/test_ui_api.py` 覆盖 task list、task creation、settings、detail runtime/test logs、structured test metadata、human review、HTTP static/API endpoints 等后端 view-model 和 HTTP 行为。见 `tests/test_ui_api.py:149` 到 `tests/test_ui_api.py:185`、`tests/test_ui_api.py:187` 到 `tests/test_ui_api.py:260`、`tests/test_ui_api.py:349` 到 `tests/test_ui_api.py:451`。
- 当前测试文件没有直接覆盖 `agentloop/ui_static/app.js` 的 DOM 渲染结果，也没有视觉截图或 CSS 回归测试。
- 本次调查未运行完整测试套件，因为任务要求是现状调查并写 dossier；未修改生产代码。

## 3. Affected Modules

- `agentloop/ui_static/index.html`：定义 `Execution log` tab、runtime 区域和下方 `Artifacts all phases` 容器。
- `agentloop/ui_static/app.js`：负责 `renderRuntime()`、`renderArtifacts()`、artifact 分组、Markdown preview 渲染和 tab 切换。
- `agentloop/ui_static/styles.css`：负责全局主题、tab panel、runtime layout、log block、artifact list、Markdown body 和响应式规则。
- `agentloop/api.py`：负责 `build_task_detail()`、`list_task_artifacts()`、`latest_runtime_summary()` 等 UI view-model 数据。
- `agentloop/ui.py`：负责本地 HTTP API 和静态资源服务。
- `tests/test_ui_api.py`：当前主要测试入口，覆盖后端 API/view-model，不覆盖前端视觉 DOM。

## 4. Open Risks Discovered

- `Execution log` 下方信息区目前只显示 Markdown artifact。`framing.json`、`acceptance.json`、`review-*.json` 等非 Markdown 文件虽在 API artifact 列表中，但不会在 `#artifactList` 中渲染。现状来源：`agentloop/ui_static/app.js:846`。
- `artifactPhase()` 把 `review-*.json` 映射到 `Reviews`，但 `renderArtifacts()` 先过滤 `.md`，所以这个映射在当前 artifact 列表中不会产生可见 JSON review item。现状来源：`agentloop/ui_static/app.js:831` 到 `agentloop/ui_static/app.js:847`。
- `.execlog-artifacts` 仅有顶部间距，视觉结构主要依赖子级 artifact item；它和 runtime card 之间没有独立区域边界或 header 容器。现状来源：`agentloop/ui_static/styles.css:1665`、`agentloop/ui_static/index.html:90` 到 `agentloop/ui_static/index.html:93`。
- runtime 区域固定最小高度 `560px`，artifact 区域在同一个 tab panel 滚动流中位于其后；在内容较长时，下方信息区需要滚动到 runtime 区域之后才能看到。现状来源：`agentloop/ui_static/styles.css:951` 到 `agentloop/ui_static/styles.css:958`、`agentloop/ui_static/index.html:84` 到 `agentloop/ui_static/index.html:93`。
- `.markdown-body` 自身有最大高度和内部滚动，外层 `.tab-panel` 也滚动；artifact preview 内容较长时存在嵌套滚动。现状来源：`agentloop/ui_static/styles.css:561`、`agentloop/ui_static/styles.css:1438` 到 `agentloop/ui_static/styles.css:1449`。
- 前端渲染逻辑没有单元测试或截图基线；现有测试主要覆盖 API/view-model 和 HTTP 静态资源是否可访问。现状来源：`tests/test_ui_api.py:349` 到 `tests/test_ui_api.py:451`。
- 当前 git working tree 已有未由本调查产生的 `__pycache__` 修改：`agentloop/__pycache__/adapters.cpython-311.pyc`、`agentloop/__pycache__/api.cpython-311.pyc`、`agentloop/__pycache__/workflow.cpython-311.pyc`。
