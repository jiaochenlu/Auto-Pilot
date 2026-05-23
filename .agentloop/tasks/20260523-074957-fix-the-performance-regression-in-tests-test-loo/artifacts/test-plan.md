# Test Plan

## Scope

Add focused regression coverage for `tests/test_loop/duplicate_transactions.py::find_duplicate_transaction_ids` before the production performance fix. The tests preserve the current correct behavior and expose the nested-scan regression with an algorithmic call-count threshold.

## Test Files

- `tests/test_loop/test_duplicate_transactions.py`

## Cases

1. `test_returns_empty_list_when_no_duplicate_keys`
   - Verifies representative no-duplicate input returns `[]`.
2. `test_includes_first_and_later_transactions_in_duplicate_group`
   - Verifies a duplicate group includes the first occurrence and later occurrence.
3. `test_preserves_input_order_across_multiple_interleaved_duplicate_groups`
   - Verifies multiple duplicate groups are returned in original input order and unrelated transactions are omitted.
4. `test_duplicate_detection_uses_key_not_transaction_id`
   - Verifies duplicate detection is based on `(account_id, merchant, amount_cents)`, not `transaction_id`.
5. `test_large_input_uses_linear_number_of_duplicate_key_calls`
   - Builds 500 unique transactions and monkeypatches `_duplicate_key` to count calls.
   - Fails once calls exceed `len(transactions) * 3`.
   - This accepts a linear implementation that computes each key once to a few times, while failing the current $O(n^2)$ nested scan quickly.

## Commands

Run the focused regression tests:

```powershell
python -m pytest tests/test_loop/test_duplicate_transactions.py
```

Optional broader check after the implementation fix:

```powershell
python -m pytest tests/test_loop tests/test_phase2.py
```

## Expected Signals Before Fix

- The first four behavior tests should pass against the current implementation.
- `test_large_input_uses_linear_number_of_duplicate_key_calls` should fail with an assertion similar to:

```text
find_duplicate_transaction_ids exceeded the linear duplicate-key call budget: 1501 > 1500
```

## Acceptance Thresholds After Fix

- `python -m pytest tests/test_loop/test_duplicate_transactions.py` exits with code 0.
- The large-input regression test completes without exceeding `3n` `_duplicate_key` calls for `n = 500` transactions.
- Returned IDs remain exactly ordered for the representative behavior cases.
- No production implementation changes are included in this tester step.

## Evidence - Iteration 1

### Implementation Review

`tests/test_loop/duplicate_transactions.py::find_duplicate_transaction_ids` now uses a two-pass dictionary-count implementation:

- First pass computes each transaction's duplicate key once, stores the key, and increments a count in `key_counts`.
- Second pass preserves input order by zipping original transactions with their cached keys and returning IDs whose key count is greater than 1.
- This avoids the prior nested scan shape and gives linear duplicate-key work.

### Focused Pytest Attempt

Command:

```powershell
python -m pytest tests/test_loop/test_duplicate_transactions.py -q
```

Exit code: `1`

Important output:

```text
C:\Python311\python.exe: No module named pytest
```

Command:

```powershell
py -m pytest tests/test_loop/test_duplicate_transactions.py -q
```

Exit code: `1`

Important output:

```text
C:\Python311\python.exe: No module named pytest
```

Pytest could not be run because the only available Python installation does not have `pytest` installed and this repository has no dependency lockfile or requirements file available in the workspace.

### Fallback Behavioral And Performance Harness

Command:

```powershell
@'
import sys
import time
sys.path.insert(0, r"tests/test_loop")
import duplicate_transactions

def tx(transaction_id, account_id, merchant, amount_cents):
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "merchant": merchant,
        "amount_cents": amount_cents,
    }

cases = [
    ([tx("tx-001", "acct-1", "Coffee", 450), tx("tx-002", "acct-1", "Coffee", 550), tx("tx-003", "acct-2", "Coffee", 450), tx("tx-004", "acct-1", "Bakery", 450)], []),
    ([tx("tx-001", "acct-1", "Coffee", 450), tx("tx-002", "acct-2", "Bakery", 800), tx("tx-003", "acct-1", "Coffee", 450)], ["tx-001", "tx-003"]),
    ([tx("tx-001", "acct-1", "Coffee", 450), tx("tx-002", "acct-2", "Market", 1200), tx("tx-003", "acct-3", "Fuel", 5000), tx("tx-004", "acct-1", "Coffee", 450), tx("tx-005", "acct-4", "Coffee", 450), tx("tx-006", "acct-2", "Market", 1200), tx("tx-007", "acct-2", "Market", 1200)], ["tx-001", "tx-002", "tx-004", "tx-006", "tx-007"]),
    ([tx("tx-001", "acct-1", "Pharmacy", 2100), tx("tx-999", "acct-1", "Pharmacy", 2100), tx("tx-001", "acct-9", "Pharmacy", 2100)], ["tx-001", "tx-999"]),
]

for index, (transactions, expected) in enumerate(cases, 1):
    actual = duplicate_transactions.find_duplicate_transaction_ids(transactions)
    assert actual == expected, (index, actual, expected)

original_duplicate_key = duplicate_transactions._duplicate_key
call_count = 0
transactions = [tx(f"tx-{i:05d}", f"acct-{i}", "Unique", i) for i in range(500)]

def counting_duplicate_key(transaction):
    global call_count
    call_count += 1
    return original_duplicate_key(transaction)

duplicate_transactions._duplicate_key = counting_duplicate_key
try:
    assert duplicate_transactions.find_duplicate_transaction_ids(transactions) == []
finally:
    duplicate_transactions._duplicate_key = original_duplicate_key
assert call_count == len(transactions), (call_count, len(transactions))

large = [tx(f"tx-{i:07d}", f"acct-{i}", "Unique", i) for i in range(100000)]
start = time.perf_counter()
result = duplicate_transactions.find_duplicate_transaction_ids(large)
elapsed = time.perf_counter() - start
assert result == []
print(f"behavior_cases=4 passed")
print(f"key_calls_for_500={call_count}")
print(f"large_unique_n=100000 elapsed_seconds={elapsed:.4f} duplicates={len(result)}")
'@ | python -
```

Exit code: `0`

Important output:

```text
behavior_cases=4 passed
key_calls_for_500=500
large_unique_n=100000 elapsed_seconds=0.0693 duplicates=0
```

### Remaining Gaps

- The focused pytest suite could not be executed in this environment because `pytest` is not installed.
- The fallback harness covered the same four behavior cases, verified exactly one `_duplicate_key` call per transaction for `n = 500`, and captured timing for `n = 100000` unique transactions.
