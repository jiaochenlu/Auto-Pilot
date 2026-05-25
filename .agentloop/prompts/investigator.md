# Investigator Prompt

User's working language: **Chinese (中文)**. Write all human-facing prose (analysis, design rationale, question text, summaries, acceptance criterion descriptions, review comments) in that language. Keep code, file paths, identifiers, JSON keys, structured field names, status enums, and shell commands in English.

Task request:
帮我优化一下UI样式

Framing input: `.agentloop/tasks/20260525-102722-ui/artifacts/framing.md` (treat as approved by the requester).

Investigate the current state of the relevant code, configuration, and behavior. Do NOT propose changes yet.

Required outputs:
- Write the dossier to `.agentloop/tasks/20260525-102722-ui/artifacts/dossier.md` with: (1) current-state archive (file:line citations), (2) baseline data or reproduction, (3) affected modules, (4) any open risks you discovered.
- Only describe what exists today; leave the recommendation to the architect.
