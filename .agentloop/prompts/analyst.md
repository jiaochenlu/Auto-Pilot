# Analyst Prompt

Task request:
Fix the performance regression in tests/test_loop/duplicate_transactions.py. The function find_duplicate_transaction_ids currently produces correct results but is too slow on large inputs.

Analyze this specific task. Do not use generic AgentLoop acceptance criteria unless they are directly required by the task.

Required outputs:
- Write task-specific analysis to `.agentloop/tasks/20260523-095536-fix-the-performance-regression-in-tests-test-loo/artifacts/analysis.md`. Include goal, non-goals, assumptions, risks, and open questions.
- Include a `Verification Plan` section in the analysis. For bug, regression, performance, or code-change tasks, name the focused tests or test files that should prove the fix.
- Write human-readable task-specific acceptance criteria to `.agentloop/tasks/20260523-095536-fix-the-performance-regression-in-tests-test-loo/artifacts/acceptance.md`.
- Write structured acceptance criteria JSON to `.agentloop/tasks/20260523-095536-fix-the-performance-regression-in-tests-test-loo/artifacts/acceptance.json`.

The JSON must be an object with `acceptance_criteria`, an array of objects containing: id, description, verification, required, status, evidence. Use status `pending`.
For bug, regression, performance, slow, timeout, or code-change tasks, include at least one required criterion with verification `automated_test`; its evidence should name the expected regression test file or command.
Stop after producing these files; execution starts only after requester approval.
