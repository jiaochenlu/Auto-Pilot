# Architect Prompt (pre-approval)

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

### From `investigator` (turn 1)
通读 lifecycle (styles.css:408-529 + app.js:213-273) 与 execution log (styles.css:1052-1208,1765,1780-1781 + app.js:990-1029,1337-1406) 的全部 CSS 规则与 JS 渲染契约，确认 :root token 与 reused class 全局规则，写出现状档案、15 条可观察问题与 8 项风险。

**Decisions made:**
- 把 pre.command-block / pre.log-block 在 styles.css 中‘无独立规则、继承浏览器默认’这一事实当作可观察现状记入（第 5 节第 13 条），并标注为 architect 改动时最显眼短板。 — _why:_ grep 在 styles.css 全文未匹配到独立的 .command-block / .log-block 选择器，但 app.js:1399/1405 实际渲染了这两个 pre；这是 execution log 当前最直接的视觉问题，但 framing 没显式提及，必须在 research 落档以免被忽略。
- 把 lifecycle 连线 top:46px / left:18px 与圆点尺寸、label padding 的耦合显式列为 R1 风险，强烈建议 architect 在 proposal 中把这条耦合写成约束。 — _why:_ 这是 lifecycle 改动最容易翻车的点：任何对 .lc-label 字号 / .lc-dot 尺寸 / .lc-btn padding 的调整都会让水平连线脱离圆点中线；framing 没显式提醒。
- 把 lc-dot-pulse box-shadow 覆盖 lc-current 静态光晕这一事实写入 R2，并要求 architect 测试三态过渡（current 非 running → current running → done）。 — _why:_ 脉动 keyframes 与 .lc-current 的静态 box-shadow 在同一属性上叠加，浏览器会用 animation 覆盖静态值；如果方案把光晕拆出来（例如挪到 outline 或 ::before），动画停止瞬间圆点尺寸可能跳变，必须实测。
- 用 R4 强调 .artifact-item/.artifact-head/.task-sub/.section-head 的全局规则不可动，所有 execlog 内视觉调整必须用 .execlog-artifacts <selector> 形式限定，并列出 app.js 中所有使用 .task-sub 的位置以量化污染风险。 — _why:_ framing assumption 第 6 条已写过这条约束，但只是定义级别；research 阶段必须把 app.js 中 .task-sub 出现的全部行号点名（66/77/80/453/511/521/686/927/938/942/995/1011/1019/1127/1152/1219/1345/1376/1418/1430/1437/1459/1460/1474/1484），让 architect/implementer 直观感受‘改全局 = 全站塌方’的范围。
- 不做截图基线、不跑 dev server。 — _why:_ framing 成功判定为‘面板边界’，视觉量化基线非必需；本轮调研无需启动应用即可完整描述现状。如 architect 需要 before/after 对比再单独用 run 技能截图，避免现在浪费工时。

**Open concerns flagged for you:**
- R1: lifecycle 连线 top:46px / left:18px 是 magic number，依赖 .lc-label 字号 + .lc-dot 尺寸 + .lc-btn padding。proposal 如改这三者中任一，必须同时给出新的 top/left 数值，否则连线会脱节。
- R2: .lc-current .lc-dot 的静态 box-shadow 与 @keyframes lc-dot-pulse 在同一属性上叠加，动画期间静态值被覆盖、停止瞬间被静态值接管。如要拆静态/动画光晕（挪到 outline 或 ::before），必须实测 current-非 running → current-running → done 三态过渡，避免圆点尺寸跳变。
- R3: .lc-running .lc-sub::after 的 ' · working…' 文案是纯 CSS 注入；改 .lc-sub 选择器或 ::after content 时必须保留这条提示，它是用户感知‘在跑’的关键线索。
- R4: .artifact-item/.artifact-head/.task-sub/.section-head 的全局规则不可动。execlog 内的样式调整必须写成 .execlog-artifacts <selector> 这种祖先限定形式；不能改 styles.css:277-294 / 980-1012 / 1611-1615 的全局规则，否则会影响 basic tab、phase-artifact、acceptance、settings 等多处面板。
- R5: @keyframes spin (styles.css:1770) 被 .lc-running .lc-dot::after 与全局 .spinner 共用，不可改名/改行为；新动画请新增带 lc- / rt- 前缀的 @keyframes。
- R6: execution log 内部已存在三套绿色/红色 (#16a34a/#166534/#dcfce7 vs #dc2626/#991b1b/#fee2e2 vs :root --green/--red)。如要统一，只允许走现有 :root token 或新增 --rt-* 局部 token；不允许改 :root 色值（framing 明令禁止）。
- R7: pre.command-block / pre.log-block 在 styles.css 中无独立规则，目前继承浏览器默认 pre 样式（无背景/无 padding/无 white-space wrap）。如新增样式必须用 .runtime-content pre.command-block 之类祖先限定，避免和 .markdown-body 内的 pre 规则冲突 — proposal 前请再 grep 一次 .markdown-body pre 防止规则覆盖。
- R8: lifecycle 在窄屏 (<~760px detail 列宽) 会触发 overflow-x:auto 横滚；@media (max-width:900px) 块未对它做回落。如要补回落仍在面板边界内，请决定是否处理；不补则保留现状横滚行为。
- 信息冗余: .runtime-tabs 的 .rt-iter 每行都重复同一个 Iteration N（app.js:1386），与 .iteration-bar 的 active chip 信息重复，proposal 可考虑是否在 runtime-tabs 内隐藏。

**Reference files:** `.agentloop/tasks/20260526-064045-ui/artifacts/research.md`, `.agentloop/tasks/20260526-064045-ui/artifacts/framing.md`, `.agentloop/tasks/20260526-064045-ui/artifacts/framing.json`, `.agentloop/tasks/20260526-064045-ui/artifacts/handoff/framer-001.json`, `.agentloop/tasks/20260526-064045-ui/artifacts/handoff/framer-002.json`, `agentloop/ui_static/styles.css#L408-L529`, `agentloop/ui_static/styles.css#L1052-L1208`, `agentloop/ui_static/styles.css#L1765`, `agentloop/ui_static/styles.css#L1780-L1781`, `agentloop/ui_static/styles.css#L1-L38`, `agentloop/ui_static/styles.css#L277-L294`, `agentloop/ui_static/styles.css#L980-L1012`, `agentloop/ui_static/styles.css#L1611-L1615`, `agentloop/ui_static/styles.css#L1524-L1545`, `agentloop/ui_static/styles.css#L1770`, `agentloop/ui_static/index.html#L56`, `agentloop/ui_static/index.html#L85-L95`, `agentloop/ui_static/app.js#L160-L166`, `agentloop/ui_static/app.js#L213-L273`, `agentloop/ui_static/app.js#L990-L1029`, `agentloop/ui_static/app.js#L1337-L1406`

Read the upstream handoff carefully before producing your output. Resolve any flagged concerns or call them out explicitly in your own handoff.

Task request:
帮我优化一下UI样式

Inputs: `.agentloop/tasks/20260526-064045-ui/artifacts/framing.md`, `.agentloop/tasks/20260526-064045-ui/artifacts/research.md`.

Required outputs:
- `.agentloop/tasks/20260526-064045-ui/artifacts/proposal.md` — recommended approach, alternatives considered, risks.
- `.agentloop/tasks/20260526-064045-ui/artifacts/acceptance.md` — human-readable acceptance criteria.
- `.agentloop/tasks/20260526-064045-ui/artifacts/acceptance.json` — structured `{acceptance_criteria: [{id, description, verification, required, status, evidence}]}`.
- `.agentloop/tasks/20260526-064045-ui/artifacts/test-plan.md` — pre-implementation test plan with required evidence and reviewer gate.

For bug, regression, performance, slow, timeout, or code-change tasks, include at least one required criterion with verification `automated_test`.
Stop after producing these files; execution starts only after the requester approves.

## Handoff contract (mandatory)

In addition to the artifacts above, you MUST write a JSON handoff package to `.agentloop/tasks/20260526-064045-ui/artifacts/handoff/architect-001.json`.
This file is what the next role reads. Use exactly this schema:

```json
{
  "schema_version": 1,
  "role": "architect",
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
