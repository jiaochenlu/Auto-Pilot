# UI 样式优化验收标准

## 必须满足

- AC-001：`Execution log` 下方的 `Artifacts all phases` 区域具有明确的视觉边界、标题层级和内容组织，不再只是依赖子项卡片自然堆叠。
- AC-002：artifact phase 分组在视觉上可快速扫描，阶段标题、文件数量和 artifact item 之间的层级关系清晰。
- AC-003：artifact item 的文件名、大小、截断提示和 Markdown preview 可读性提升，长文件名和长 preview 不造成文本重叠或布局破裂。
- AC-004：优化后的样式与现有浅色工作台 UI 保持一致，复用现有 CSS variables、圆角、边框和阴影体系，不引入新的 UI 库、图标库或构建步骤。
- AC-005：在桌面宽度和 `max-width: 900px` 响应式宽度下，artifact 区域保持可读、可滚动，header/meta 不互相挤压。
- AC-006：自动化测试必须通过，至少覆盖本地 UI 静态/API 基础行为或关键 artifact 区域选择器，证明改动没有破坏 UI 服务与任务详情渲染入口。
- AC-007：实现不得改变 runtime log、artifact API 数据语义、任务执行逻辑或非 Markdown artifact 的可见性策略，除非另有审批。

## 应提供的证据

- 自动化测试命令和通过结果。
- 桌面视口下 `Execution log` tab 的人工检查截图或明确检查记录。
- 窄屏视口下 artifact 区域的人工检查截图或明确检查记录。
- 变更文件清单，确认未引入新前端依赖。

## 非目标

- 不要求重新设计 `Execution log` runtime 区域本身。
- 不要求展示当前被过滤掉的 `.json` artifact。
- 不要求新增业务功能、后端字段或任务状态。
