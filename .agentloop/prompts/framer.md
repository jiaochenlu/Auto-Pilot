# Framer Prompt

User's working language: **Chinese (中文)**. Write all human-facing prose (analysis, design rationale, question text, summaries, acceptance criterion descriptions, review comments) in that language. Keep code, file paths, identifiers, JSON keys, structured field names, status enums, and shell commands in English.

Task request:
帮我优化一下UI样式

Frame the problem so research and implementation can later proceed without ambiguity. Do NOT propose a solution yet.

Prior Q&A:
- Q-FILES: 需要 AgentLoop 优先调查哪些文件、模块或子系统？ (answer: execution log 下面的信息布局)
- Q-OUTCOME: 从请求者视角看，怎样才算优化成功？是否有需要排除在范围外的非目标？ (answer: 需要提出 UI 设计方案或视觉风格建议)

Required outputs:
- Write a human-readable framing to `.agentloop/tasks/20260525-102722-ui/artifacts/framing.md` (problem statement, non-goals, assumptions, open questions).
- Write structured framing JSON to `.agentloop/tasks/20260525-102722-ui/artifacts/framing.json` with the schema {problem_statement, non_goals[], assumptions[], open_questions[{id,question,blocking,reason,answer}], ready_for_research}.
- Leave `answer` as an empty string ("") when the requester has not answered. Do NOT write placeholder text like "unanswered", "n/a", or "tbd".
- Set `ready_for_research` to true only when no blocking question is unanswered.
- Stop after producing these two files; research starts only after the requester clicks "Start research".
