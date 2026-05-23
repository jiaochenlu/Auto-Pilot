"""Small performance-regression exercise for agentloop testing."""


def find_duplicate_transaction_ids(transactions):
    """Return IDs for transactions that share the same account, merchant, and amount.

    The result must preserve the original input order. A transaction is considered
    a duplicate when at least one other transaction has the same duplicate key.
    """
    key_counts = {}
    keys = []
    for transaction in transactions:
        key = _duplicate_key(transaction)
        keys.append(key)
        key_counts[key] = key_counts.get(key, 0) + 1

    return [
        transaction["transaction_id"]
        for transaction, key in zip(transactions, keys)
        if key_counts[key] > 1
    ]


def _duplicate_key(transaction):
    return (
        transaction["account_id"],
        transaction["merchant"],
        transaction["amount_cents"],
    )
