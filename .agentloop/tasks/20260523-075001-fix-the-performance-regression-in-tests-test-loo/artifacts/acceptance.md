# Acceptance Criteria

1. `find_duplicate_transaction_ids` in `tests/test_loop/duplicate_transactions.py` preserves the existing duplicate definition: transactions are duplicates when they share the same `account_id`, `merchant`, and `amount_cents`.

2. The function returns the `transaction_id` for every transaction that belongs to a duplicate group, including the first occurrence in that group.

3. Returned transaction IDs preserve the original input order.

4. Unique transactions are not included in the returned list.

5. The implementation avoids the current nested full-list scan and handles large inputs in linear or near-linear time using built-in Python data structures.

6. Focused automated tests prove both correctness and the performance regression fix. The expected focused verification is `python -m pytest tests/test_loop/test_duplicate_transactions.py`; if that source file is absent, execution should add or restore it with large-input regression coverage.

7. The fix remains narrowly scoped to `tests/test_loop/duplicate_transactions.py` and any focused duplicate-transaction tests needed to verify the regression.
