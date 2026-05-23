# Reviewer Prompt

Task: Fix the performance regression in tests/test_loop/duplicate_transactions.py.

The function find_duplicate_transaction_ids currently produces correct results but is too slow on large inputs.
Iteration: 1
Task artifact directory: `.agentloop/tasks/20260523-074957-fix-the-performance-regression-in-tests-test-loo/artifacts/`
Use paths exactly as written. Do not write task artifacts to `.agentloop/artifacts/`.

Review the result against acceptance criteria and write strict JSON to `.agentloop/tasks/20260523-074957-fix-the-performance-regression-in-tests-test-loo/artifacts/review-001.json`.
The JSON object must include: decision, summary, open_medium_high_count, comments, acceptance_results, and test_results. Use decision APPROVED, CHANGES_REQUIRED, or BLOCKED.
Do not use APPROVED if any required automated/unit/test acceptance criterion lacks an executed test result with exit_code 0. If a test could not run, report CHANGES_REQUIRED or BLOCKED and include the reason in comments and test_results.
Do not use APPROVED for bug, regression, performance, slow, or timeout tasks unless the work added or updated a focused regression/performance test and the review records passing evidence for it.
