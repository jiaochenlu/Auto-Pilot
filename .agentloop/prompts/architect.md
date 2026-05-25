# Architect Prompt (pre-approval)

User's working language: **Chinese (中文)**. Write all human-facing prose (analysis, design rationale, question text, summaries, acceptance criterion descriptions, review comments) in that language. Keep code, file paths, identifiers, JSON keys, structured field names, status enums, and shell commands in English.

Task request:
帮我优化一下UI样式

Inputs: `.agentloop/tasks/20260525-102722-ui/artifacts/framing.md`, `.agentloop/tasks/20260525-102722-ui/artifacts/dossier.md`.

Required outputs:
- `.agentloop/tasks/20260525-102722-ui/artifacts/proposal.md` — recommended approach, alternatives considered, risks.
- `.agentloop/tasks/20260525-102722-ui/artifacts/acceptance.md` — human-readable acceptance criteria.
- `.agentloop/tasks/20260525-102722-ui/artifacts/acceptance.json` — structured `{acceptance_criteria: [{id, description, verification, required, status, evidence}]}`.
- `.agentloop/tasks/20260525-102722-ui/artifacts/test-plan.md` — pre-implementation test plan with required evidence and reviewer gate.

For bug, regression, performance, slow, timeout, or code-change tasks, include at least one required criterion with verification `automated_test`.
Stop after producing these files; execution starts only after the requester approves.
