# Acceptance Criteria: Duplicate transaction performance fix

## Required

1. `find_duplicate_transaction_ids` returns transaction IDs for all transactions whose `(account_id, merchant, amount_cents)` key appears more than once.
2. Returned transaction IDs preserve the original input order, including interleaved duplicate groups.
3. The first transaction in each duplicate group is included along with later matching transactions.
4. Duplicate detection is based only on `account_id`, `merchant`, and `amount_cents`, not on `transaction_id`.
5. The implementation avoids superlinear duplicate-key work on large inputs and satisfies the existing linear duplicate-key call budget.
6. The focused regression tests pass with `python -m pytest tests/test_loop/test_duplicate_transactions.py`.

## Out of Scope

- Changes to unrelated AgentLoop functionality.
- Changes to CLI commands, runtime configuration, task lifecycle behavior, or documentation outside this focused regression.
- New dependencies or broad rewrites unrelated to `find_duplicate_transaction_ids`.

