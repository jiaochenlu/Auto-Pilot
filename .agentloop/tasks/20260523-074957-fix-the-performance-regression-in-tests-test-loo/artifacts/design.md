# Design: Fix Performance Regression in `find_duplicate_transaction_ids`

## Problem Summary

`tests/test_loop/duplicate_transactions.py::find_duplicate_transaction_ids` is correct but runs in O(n²): for each transaction it rescans the entire list and recomputes `_duplicate_key` on every pair. On large inputs this dominates runtime. The fix is to replace the nested scan with a two-pass linear algorithm that counts duplicate keys, then filters the input in order.

## Goals

- Reduce time complexity from O(n²) to O(n) (expected hash-table behavior).
- Preserve the externally observable contract:
  - Duplicate key = `(account_id, merchant, amount_cents)`.
  - A transaction is returned iff its key appears at least twice in the input.
  - Returned IDs preserve original input order (including the first occurrence of each duplicate group).
  - Input dictionary shape unchanged.

## Non-Goals

Per analysis: no data-model changes, no duplicate-definition changes, no broader perf work, no AgentLoop lifecycle changes.

## Approach

Two-pass algorithm in the same module, same function signature:

1. **Pass 1 — count:** iterate `transactions` once, computing `_duplicate_key(t)` per element, and accumulate counts in a `dict[key, int]` (or `collections.Counter` built from a generator). Single key computation per transaction.
2. **Pass 2 — filter in order:** iterate `transactions` again; for each, recompute the key (or cache from pass 1) and append `transaction["transaction_id"]` to the result list when `counts[key] >= 2`.

Both passes are O(n) with O(n) auxiliary space. `_duplicate_key` is kept as-is (AC-5).

### Key-caching variant (chosen)

To avoid double-computing `_duplicate_key`, precompute keys once into a list aligned with `transactions`:

```python
def find_duplicate_transaction_ids(transactions):
    keys = [_duplicate_key(t) for t in transactions]
    counts = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    return [
        t["transaction_id"]
        for t, k in zip(transactions, keys)
        if counts[k] >= 2
    ]
```

This is one pass to build `keys`, one pass to count, one pass to filter — still O(n), with each `_duplicate_key` invoked exactly once per transaction (addresses analysis open question #2 implicitly by minimizing key computation; an explicit call-count assertion is left to the test layer).

## Test Plan

Add `tests/test_loop/test_duplicate_transactions.py` (new file; ensure `tests/test_loop/__init__.py` exists or use direct import via package path already used by other `test_loop` tests). Cases:

1. **No duplicates** → empty list.
2. **Single duplicate pair** including the first transaction → both IDs returned in input order.
3. **Multiple duplicate groups, interleaved** → all duplicate IDs returned in input order; non-duplicates omitted.
4. **Duplicate key but distinct `transaction_id`** → both IDs returned (key is account/merchant/amount, not ID).
5. **Order preservation** → assert exact list equality, not set equality.
6. **Large-input regression (AC-3):** build N≈50,000 transactions where ~half share keys; assert the call completes under a generous wall-clock bound (e.g., 2.0s) using `time.perf_counter`. The bound is loose enough for slow CI but well below the O(n²) runtime (which would take many seconds to minutes at this N).

Optional hardening: monkeypatch `_duplicate_key` with a counter wrapper and assert it is called O(n) times, not O(n²). Recommended to lock in the regression deterministically without timing flakiness.

## Risks & Mitigations

- **Off-by-one on "first occurrence":** mitigated by `counts[k] >= 2` filter applied during the in-order second pass — the first element of each duplicate group is naturally included.
- **Timing-flaky CI:** mitigated by generous timeout plus optional call-count assertion.
- **Hashability:** all key components are scalars (str/int) per existing usage — safe to hash.
- **Package import:** if `tests/test_loop` lacks `__init__.py`, add an empty one so the test file is collected uniformly.

## Files Touched

- `tests/test_loop/duplicate_transactions.py` — rewrite `find_duplicate_transaction_ids` body; keep `_duplicate_key` unchanged.
- `tests/test_loop/test_duplicate_transactions.py` — new test file covering AC-1, AC-2, AC-3.
- `tests/test_loop/__init__.py` — add if missing.

## Verification

- `python -m pytest tests/test_loop/test_duplicate_transactions.py` — must pass (AC-1, AC-2, AC-3).
- Code review confirms linear approach and unchanged `_duplicate_key` (AC-4, AC-5).
