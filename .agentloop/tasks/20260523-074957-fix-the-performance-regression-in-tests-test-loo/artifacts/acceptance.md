# Acceptance Criteria

## Task

Fix the performance regression in `tests/test_loop/duplicate_transactions.py` for `find_duplicate_transaction_ids`.

## Criteria

| ID | Required | Verification | Criterion | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| AC-1 | yes | automated_test | `find_duplicate_transaction_ids` returns the same duplicate transaction IDs as the current implementation for representative inputs: no duplicates, one duplicate group, multiple duplicate groups, and duplicate groups where the first occurrence must be included. | pending | `python -m pytest tests/test_loop/test_duplicate_transactions.py` |
| AC-2 | yes | automated_test | Returned transaction IDs preserve original input order. | pending | `python -m pytest tests/test_loop/test_duplicate_transactions.py` |
| AC-3 | yes | automated_test | A large-input regression test proves the function handles many transactions without the previous nested-scan slowdown. | pending | `python -m pytest tests/test_loop/test_duplicate_transactions.py` |
| AC-4 | yes | functional_review | The implementation avoids the $O(n^2)$ pairwise scan and uses a linear-time approach such as counting duplicate keys before filtering IDs in input order. | pending | code review of `tests/test_loop/duplicate_transactions.py` |
| AC-5 | yes | functional_review | The duplicate key remains exactly `(account_id, merchant, amount_cents)` and the function continues to expect the existing transaction dictionary shape. | pending | code review of `_duplicate_key` usage in `tests/test_loop/duplicate_transactions.py` |
| AC-6 | yes | human_review | Requester reviews and approves this task-specific analysis and acceptance criteria before execution starts. | pending | `.agentloop/tasks/20260523-074957-fix-the-performance-regression-in-tests-test-loo/artifacts/analysis.md` |

## Approval Instruction

Review this file together with `.agentloop/tasks/20260523-074957-fix-the-performance-regression-in-tests-test-loo/artifacts/analysis.md`. Execution should start only after requester approval.
