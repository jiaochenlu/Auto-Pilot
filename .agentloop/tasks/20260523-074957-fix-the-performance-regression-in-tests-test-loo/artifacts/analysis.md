# Task Analysis

## Goal

Fix the performance regression in `tests/test_loop/duplicate_transactions.py` by making `find_duplicate_transaction_ids(transactions)` scale efficiently on large inputs while preserving its current externally visible behavior.

The current implementation is correct but performs a nested scan across the full transaction list for every transaction. That makes the function roughly $O(n^2)$ and repeatedly recomputes duplicate keys. The intended fix should identify duplicate keys in linear time, then return only the transaction IDs whose `(account_id, merchant, amount_cents)` key appears more than once, preserving the original input order.

## Non-Goals

- Do not redesign transaction data models or add validation for malformed transaction dictionaries.
- Do not change the duplicate definition: duplicates are based only on `account_id`, `merchant`, and `amount_cents`.
- Do not change result ordering: returned IDs must remain in original input order.
- Do not add AgentLoop lifecycle, CLI, or runtime changes.
- Do not broaden this into generic performance work outside `tests/test_loop/duplicate_transactions.py` and its focused regression tests.

## Assumptions

- Every transaction contains `transaction_id`, `account_id`, `merchant`, and `amount_cents`, matching the existing function's expectations.
- Transaction keys are hashable because they are currently assembled into a tuple of scalar fields.
- The function is allowed to use standard-library data structures such as `dict`, `set`, or `collections.Counter`.
- A focused test file should exist or be added for this helper, most likely `tests/test_loop/test_duplicate_transactions.py`.
- Large-input performance should be verified with a bounded regression test that is stable in CI, not an overly tight wall-clock benchmark.

## Risks

- A one-pass implementation can accidentally include only later duplicates and omit the first transaction in each duplicate group; the current behavior includes all transactions whose key appears at least twice.
- Using an unordered data structure for output would violate the required original input ordering.
- A brittle timing-only test could fail on slower CI machines; prefer a test that uses large input plus a reasonable timeout or demonstrates linear behavior without depending on tiny timing margins.
- If tests import from `tests/test_loop/duplicate_transactions.py` directly, naming and package layout must be handled without assuming `tests/test_loop` is already a Python package.

## Open Questions

1. Is there an existing hidden performance threshold the implementation must satisfy, or should the fix target a clear linear-time algorithm with a focused large-input regression test?
2. Should the regression test assert only acceptable completion on large input, or also instrument `_duplicate_key` call counts to prevent a future nested-scan regression?
3. Should `merchant` comparison remain exact and case-sensitive, as it is today?

## Verification Plan

- Run the focused duplicate transaction tests: `python -m pytest tests/test_loop/test_duplicate_transactions.py`.
- If the focused test file does not exist, add it with cases for no duplicates, duplicate groups including the first item, multiple duplicate groups, order preservation, and a large-input performance regression case.
- Optionally run the broader relevant suite after the focused test passes: `python -m pytest tests/test_loop tests/test_phase2.py`.
