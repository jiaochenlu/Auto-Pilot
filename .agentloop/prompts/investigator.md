# Investigator Prompt

User's working language: **Chinese (中文)**. Write all human-facing prose (analysis, design rationale, question text, summaries, acceptance criterion descriptions, review comments) in that language. Keep code, file paths, identifiers, JSON keys, structured field names, status enums, and shell commands in English.

Task code path: `C:/Users/chenlujiao/OneDrive - Microsoft/Documents/AutoPilot` (directory). Treat it as the working directory and limit analysis to files under it unless the task explicitly requires looking elsewhere. All file paths cited in your output must be relative to this directory.

## Upstream handoff

### From `framer` (turn 2)
应用请求方答复，把范围收窄到 lifecycle 与 execution log 两个面板，成功判定改为‘面板边界’。更新 framing.md 的问题陈述/非目标/假设/开放问题段，framing.json 的对应字段，ready_for_research 置为 true。

**Decisions made:**
- 把目标面板硬性绑定到 lifecycle (.lifecycle + .lc-* + @keyframes lc-dot-pulse / spin) 和 execution log (#execlogTab 内部全部 class)，并在 non_goals 中显式列出禁止改动的其他 UI 区域。 — _why:_ 请求方选了 B 局部痛点修复并点名两个面板，又选 (4) 面板边界作为成功判定。明确‘禁区清单’比‘做什么’更重要，能让 research/implementer/reviewer 都用同一把尺子判断是否越界。
- 对复用 class（.artifact-item、.artifact-head、.task-sub、.section-head 等）要求通过更窄祖先选择器限定，不得修改其全局规则。 — _why:_ Execution log 底部 artifact 区复用了 basic tab 同名 class；若直接改全局规则会污染其他面板，违反面板边界。该约束必须在 framing 就写死，否则 research 阶段容易忽略。
- 禁止改全局 :root token，只允许新增带前缀的局部变量（--lc-*、--rt-*）。 — _why:_ :root token 被全 UI 共享，改任何一条都会溢出到其他面板，与‘面板边界’直接冲突。局部前缀变量是兼顾可维护性与边界约束的折中。
- Q-FILES 直接基于代码现状给出具体行段与搜索关键字，作为 research 起点。 — _why:_ 请求方没单独答 Q-FILES，但范围已明确，给出精确行段能让 research 立刻聚焦，避免重读全文件。
- ready_for_research = true。 — _why:_ 两个阻塞问题均已答复，Q-FILES 非阻塞且已自答。可以进入 research。

**User answers applied:**
- Q-SCOPE: B. 局部痛点修复（lifecycle、execution log）
- Q-OUTCOME: (4) 本轮要触达的页面 / 面板边界

**Open concerns flagged for you:**
- 面板边界是本轮唯一硬约束——研究、设计、实施的每一个产物都必须能回答‘这条改动是否落在 .lifecycle / #execlogTab 内’。若 reseacher 发现需要触碰其他面板才能完成优化，必须先回到 framer 扩范围，不能擅自越界。
- 复用 class 的窄化要求容易被忽略：.artifact-item / .artifact-head / .task-sub / .section-head 在 basic tab 与 execution log 都用，必须用 .execlog-artifacts <selector> 这种祖先限定写法，不能改全局规则。
- lifecycle 的 @keyframes (lc-dot-pulse、spin) 与 .iter-chip.is-latest::after 的伪元素文案被 JS 状态依赖；若改动涉及动画或伪元素，需要在 app.js 中确认状态切换时机不被破坏。
- 请求方没指定视觉对标对象，research 阶段需要自己识别面板内部的具体痛点（如对齐、密度、连线断点、动画节奏、颜色对比等）。建议在 research 产物里先列‘可观察问题清单’再给方案，便于 reviewer 校对。
- 禁止改全局 :root token 这条约束在写新色 / 新间距时最容易破——遇到必须新增的变量，统一写到 .lifecycle { ... } 或 #execlogTab { ... } 块顶部并加 --lc- / --rt- 前缀。

**Reference files:** `.agentloop/tasks/20260526-064045-ui/artifacts/framing.md`, `.agentloop/tasks/20260526-064045-ui/artifacts/framing.json`, `.agentloop/tasks/20260526-064045-ui/artifacts/handoff/framer-001.json`, `agentloop/ui_static/styles.css#L408-L529`, `agentloop/ui_static/styles.css#L1036-L1193`, `agentloop/ui_static/styles.css#L1750`, `agentloop/ui_static/index.html#L56`, `agentloop/ui_static/index.html#L85-L95`, `agentloop/ui_static/app.js`

Read the upstream handoff carefully before producing your output. Resolve any flagged concerns or call them out explicitly in your own handoff.

Task request:
帮我优化一下UI样式

Framing input: `.agentloop/tasks/20260526-064045-ui/artifacts/framing.md` (treat as approved by the requester).

Investigate the current state of the relevant code, configuration, and behavior. Do NOT propose changes yet.

Required outputs:
- Write the research to `.agentloop/tasks/20260526-064045-ui/artifacts/research.md` with: (1) current-state archive (file:line citations), (2) baseline data or reproduction, (3) affected modules, (4) any open risks you discovered.
- Only describe what exists today; leave the recommendation to the architect.

## Handoff contract (mandatory)

In addition to the artifacts above, you MUST write a JSON handoff package to `.agentloop/tasks/20260526-064045-ui/artifacts/handoff/investigator-001.json`.
This file is what the next role reads. Use exactly this schema:

```json
{
  "schema_version": 1,
  "role": "investigator",
  "turn": 1,
  "summary": "1-3 sentences: what you did this turn",
  "decisions": [
    {"what": "...", "why": "...", "alternatives_rejected": ["..."]}
  ],
  "user_answers_applied": {"Q-id": "answer text"},
  "open_concerns_for_next": ["explicit warning or hint for the next role"],
  "context_pointers": ["artifact paths you produced or rely on"]
}
```

- Keep it tight; this is for the next role, not a status report.
- Omit fields that don't apply rather than padding them.
- This file is required; the workflow will warn if it's missing.
