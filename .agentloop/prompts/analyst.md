# Analyst Prompt

Task request:
重新审视一下当前agentloop 的任务的生命周期管理，考虑多多任务并发的情况，实现更好的单任务配置和单任务管理，也允许用户进行批量配置和批量管理

Analyze this specific task. Do not use generic AgentLoop acceptance criteria unless they are directly required by the task.

Required outputs:
- Write task-specific analysis to `.agentloop/tasks/20260518-093703-agentloop/artifacts/analysis.md`. Include goal, non-goals, assumptions, risks, and open questions.
- Write human-readable task-specific acceptance criteria to `.agentloop/tasks/20260518-093703-agentloop/artifacts/acceptance.md`.
- Write structured acceptance criteria JSON to `.agentloop/tasks/20260518-093703-agentloop/artifacts/acceptance.json`.

The JSON must be an object with `acceptance_criteria`, an array of objects containing: id, description, verification, required, status, evidence. Use status `pending`.
Stop after producing these files; execution starts only after requester approval.
