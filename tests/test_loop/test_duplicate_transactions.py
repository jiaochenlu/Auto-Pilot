import duplicate_transactions


def _transaction(transaction_id, account_id, merchant, amount_cents):
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "merchant": merchant,
        "amount_cents": amount_cents,
    }


def test_returns_empty_list_when_no_duplicate_keys():
    transactions = [
        _transaction("tx-001", "acct-1", "Coffee", 450),
        _transaction("tx-002", "acct-1", "Coffee", 550),
        _transaction("tx-003", "acct-2", "Coffee", 450),
        _transaction("tx-004", "acct-1", "Bakery", 450),
    ]

    assert duplicate_transactions.find_duplicate_transaction_ids(transactions) == []


def test_includes_first_and_later_transactions_in_duplicate_group():
    transactions = [
        _transaction("tx-001", "acct-1", "Coffee", 450),
        _transaction("tx-002", "acct-2", "Bakery", 800),
        _transaction("tx-003", "acct-1", "Coffee", 450),
    ]

    assert duplicate_transactions.find_duplicate_transaction_ids(transactions) == [
        "tx-001",
        "tx-003",
    ]


def test_preserves_input_order_across_multiple_interleaved_duplicate_groups():
    transactions = [
        _transaction("tx-001", "acct-1", "Coffee", 450),
        _transaction("tx-002", "acct-2", "Market", 1200),
        _transaction("tx-003", "acct-3", "Fuel", 5000),
        _transaction("tx-004", "acct-1", "Coffee", 450),
        _transaction("tx-005", "acct-4", "Coffee", 450),
        _transaction("tx-006", "acct-2", "Market", 1200),
        _transaction("tx-007", "acct-2", "Market", 1200),
    ]

    assert duplicate_transactions.find_duplicate_transaction_ids(transactions) == [
        "tx-001",
        "tx-002",
        "tx-004",
        "tx-006",
        "tx-007",
    ]


def test_duplicate_detection_uses_key_not_transaction_id():
    transactions = [
        _transaction("tx-001", "acct-1", "Pharmacy", 2100),
        _transaction("tx-999", "acct-1", "Pharmacy", 2100),
        _transaction("tx-001", "acct-9", "Pharmacy", 2100),
    ]

    assert duplicate_transactions.find_duplicate_transaction_ids(transactions) == [
        "tx-001",
        "tx-999",
    ]


def test_large_input_uses_linear_number_of_duplicate_key_calls(monkeypatch):
    transactions = [
        _transaction(f"tx-{index:05d}", f"acct-{index}", "Unique", index)
        for index in range(500)
    ]
    original_duplicate_key = duplicate_transactions._duplicate_key
    call_count = 0
    max_allowed_calls = len(transactions) * 3

    def counting_duplicate_key(transaction):
        nonlocal call_count
        call_count += 1
        if call_count > max_allowed_calls:
            raise AssertionError(
                "find_duplicate_transaction_ids exceeded the linear duplicate-key "
                f"call budget: {call_count} > {max_allowed_calls}"
            )
        return original_duplicate_key(transaction)

    monkeypatch.setattr(
        duplicate_transactions,
        "_duplicate_key",
        counting_duplicate_key,
    )

    assert duplicate_transactions.find_duplicate_transaction_ids(transactions) == []
    assert call_count <= max_allowed_calls
