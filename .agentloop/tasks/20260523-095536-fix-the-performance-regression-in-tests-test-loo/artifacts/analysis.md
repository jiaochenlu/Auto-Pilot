# Analysis: Fix duplicate transaction performance regression

## Goal

Fix the performance regression in `tests/test_loop/duplicate_transactions.py` by making `find_duplicate_transaction_ids` efficient on large inputs while preserving the existing observable behavior.

The function must return every transaction ID whose transaction shares the same duplicate key with at least one other transaction. The duplicate key is the tuple of `account_id`, `merchant`, and `amount_cents`. Returned IDs must remain in original input order and must include both the first transaction in a duplicate group and all later transactions in that group.

## Non-Goals

- Do not change the transaction schema or duplicate-key definition.
- Do not change the public function name or expected return type.
- Do not broaden the task to unrelated AgentLoop behavior, CLI behavior, runtime configuration, or orchestration logic.
- Do not rewrite unrelated tests or repository structure.
- Do not introduce external dependencies for this small in-memory operation.

## Assumptions

- Input transactions are dictionaries containing `transaction_id`, `account_id`, `merchant`, and `amount_cents` keys.
- Correctness requirements are represented by `tests/test_loop/test_duplicate_transactions.py`.
- The regression is about algorithmic performance on large inputs, especially avoiding repeated scans or repeated duplicate-key computation that can grow superlinearly.
- A linear or near-linear implementation using dictionaries/sets is acceptable and expected.

## Risks

- Optimizing too aggressively could accidentally omit the first transaction in a duplicate group.
- Using unordered structures incorrectly could break the required input-order preservation.
- A fix that only passes small examples may still be too slow if it recomputes `_duplicate_key` many times per transaction.
- Mutating transaction dictionaries or depending on transaction IDs for duplicate detection would change behavior.

## Open Questions

- No open functional questions are apparent from the focused tests. If additional hidden tests exist, they are likely to emphasize large inputs, input-order preservation, and duplicate-key call count.

## Verification Plan

Run the focused regression test file:

```powershell
python -m pytest tests/test_loop/test_duplicate_transactions.py
```

This file covers:

- No duplicate keys returning an empty list.
- Duplicate groups including the first and later matching transactions.
- Input-order preservation across interleaved duplicate groups.
- Duplicate detection using `(account_id, merchant, amount_cents)` rather than `transaction_id`.
- The large-input performance regression guard: `test_large_input_uses_linear_number_of_duplicate_key_calls`.

