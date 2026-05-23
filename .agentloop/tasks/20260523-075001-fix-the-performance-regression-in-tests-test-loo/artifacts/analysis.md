# Analysis: Fix duplicate transaction performance regression

## Goal

Improve `find_duplicate_transaction_ids` in `tests/test_loop/duplicate_transactions.py` so it remains correct while handling large transaction lists efficiently.

The current implementation compares each transaction against every other transaction. That preserves the expected result, but it is quadratic in the number of transactions and becomes too slow on large inputs. The fix should reduce the duplicate detection work to a linear or near-linear pass using each transaction's duplicate key: `account_id`, `merchant`, and `amount_cents`.

## Non-Goals

- Do not change the definition of a duplicate: a transaction is duplicate only when at least one other transaction has the same `account_id`, `merchant`, and `amount_cents`.
- Do not change the returned value shape: return transaction IDs, not full transaction objects or duplicate keys.
- Do not reorder results; output must preserve the original input order for all transactions that belong to duplicate groups.
- Do not broaden the task into AgentLoop runtime, UI, workflow, or unrelated test infrastructure changes.
- Do not add external dependencies for this small algorithmic fix.

## Assumptions

- Each transaction is a mapping containing `transaction_id`, `account_id`, `merchant`, and `amount_cents`.
- The current behavior for missing required fields is acceptable: the function may raise the same kind of key lookup error rather than silently ignoring malformed data.
- Transaction IDs do not need to be unique for the algorithm to identify duplicate transaction groups; grouping is based only on account, merchant, and amount.
- The implementation may use built-in Python dictionaries, sets, or `collections.Counter` to count duplicate keys.
- A focused test file for this exercise is expected under `tests/test_loop/`, likely `tests/test_loop/test_duplicate_transactions.py`; if it is absent from source, execution should add or restore a focused test module rather than relying only on bytecode cache.

## Risks

- A faster implementation could accidentally return only the second and later members of a duplicate group instead of all members in that group.
- A set-based implementation could lose input ordering if it returns IDs while iterating over grouped keys instead of the original transaction list.
- Counting by `transaction_id` would be incorrect because duplicate membership is defined by `(account_id, merchant, amount_cents)`.
- A performance test with strict wall-clock thresholds may be flaky on slow or busy machines; verification should prefer a large enough input and a reasonable threshold, or assert algorithmic behavior where practical.
- If the focused test source file is missing, pytest may not discover the intended regression coverage until the file is recreated.

## Open Questions

- What exact large-input size or time threshold should define acceptable performance for this repository's CI environment?
- Should execution add a new source test file named `tests/test_loop/test_duplicate_transactions.py` if it is currently missing, or should tests be placed elsewhere under the existing test layout?
- Is preserving current exception behavior for malformed transaction dictionaries required, or is input validation out of scope?

## Verification Plan

- Run the focused duplicate transaction tests, expected command: `python -m pytest tests/test_loop/test_duplicate_transactions.py`.
- If no focused source test exists yet, add or restore `tests/test_loop/test_duplicate_transactions.py` with cases covering:
  - all members of duplicate groups are returned,
  - output IDs preserve original input order,
  - unique transactions are excluded,
  - a large input completes within the agreed performance bound.
- Run the implementation file's direct checks if the repository uses direct script execution for this exercise, expected command: `python tests/test_loop/duplicate_transactions.py` only if such checks are added.
- Optionally run the broader test suite with `python -m pytest` after the focused tests pass, to confirm no unrelated regression.
