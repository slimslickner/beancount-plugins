"""Tests for the block_transactions plugin."""

from beancount import loader

# Header with the accounts used across the tests. The parent brokerage account
# opts in to blocking; its sub-accounts do not.
_BASE = """\
option "operating_currency" "USD"
plugin "beancount_plugins.block_transactions"

2024-01-01 open Assets:Checking
2024-01-01 open Assets:Savings
2024-01-01 open Assets:Investment:Brokerage
    block-transactions: TRUE
2024-01-01 open Assets:Investment:Brokerage:USD
2024-01-01 open Assets:Investment:Brokerage:VOO
2024-01-01 open Assets:Investment:Unrestricted
    block-transactions: FALSE
"""


def _load(transactions: str):
    return loader.load_string(_BASE + transactions)


def _block_errors(errors):
    return [e for e in errors if "transaction-blocked account" in e.message]


# ---------------------------------------------------------------------------
# Positive cases (no error expected)
# ---------------------------------------------------------------------------


class TestAllowedTransactions:
    def test_subaccount_of_blocked_parent_is_allowed(self):
        _, errors, _ = _load(
            '2024-02-01 * "Buy VOO"\n'
            "    Assets:Investment:Brokerage:VOO  100 USD\n"
            "    Assets:Investment:Brokerage:USD  -100 USD\n"
        )
        assert _block_errors(errors) == []

    def test_nested_subaccount_is_allowed(self):
        _, errors, _ = _load(
            '2024-02-01 * "Cash sweep"\n'
            "    Assets:Investment:Brokerage:USD  500 USD\n"
            "    Assets:Checking                  -500 USD\n"
        )
        assert _block_errors(errors) == []

    def test_account_without_metadata_is_allowed(self):
        """No block-transactions key means the default (off)."""
        _, errors, _ = _load(
            '2024-02-01 * "Move to savings"\n'
            "    Assets:Savings    5 USD\n"
            "    Assets:Checking  -5 USD\n"
        )
        assert _block_errors(errors) == []

    def test_explicit_false_is_allowed(self):
        _, errors, _ = _load(
            '2024-02-01 * "Unrestricted post"\n'
            "    Assets:Investment:Unrestricted  10 USD\n"
            "    Assets:Checking                -10 USD\n"
        )
        assert _block_errors(errors) == []


# ---------------------------------------------------------------------------
# Negative cases (error expected)
# ---------------------------------------------------------------------------


class TestBlockedTransactions:
    def test_subaccount_alongside_blocked_parent_flags_only_parent(self):
        """A sub-account posting alongside the blocked parent only flags the parent."""
        _, errors, _ = _load(
            '2024-02-01 * "Mixed"\n'
            "    Assets:Investment:Brokerage      10 USD\n"
            "    Assets:Investment:Brokerage:USD  10 USD\n"
            "    Assets:Checking                 -20 USD\n"
        )
        block_errors = _block_errors(errors)
        assert len(block_errors) == 1
        assert "'Assets:Investment:Brokerage'" in block_errors[0].message

    def test_direct_posting_to_blocked_account_errors(self):
        _, errors, _ = _load(
            '2024-02-01 * "Direct post"\n'
            "    Assets:Investment:Brokerage   10 USD\n"
            "    Assets:Checking              -10 USD\n"
        )
        block_errors = _block_errors(errors)
        assert len(block_errors) == 1
        assert "'Assets:Investment:Brokerage'" in block_errors[0].message
        assert "Direct post" in block_errors[0].message

    def test_each_blocked_posting_produces_an_error(self):
        _, errors, _ = _load(
            '2024-02-01 * "Double"\n'
            "    Assets:Investment:Brokerage   10 USD\n"
            "    Assets:Investment:Brokerage    5 USD\n"
            "    Assets:Checking              -15 USD\n"
        )
        assert len(_block_errors(errors)) == 2

    def test_error_has_source_location(self):
        _, errors, _ = _load(
            '2024-02-01 * "Direct post"\n'
            "    Assets:Investment:Brokerage   10 USD\n"
            "    Assets:Checking              -10 USD\n"
        )
        error = _block_errors(errors)[0]
        assert error.source["filename"] == "<string>"
        assert error.source["lineno"] > 0

    def test_multiple_blocked_accounts_each_error(self):
        ledger = (
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.block_transactions"\n'
            "\n"
            "2024-01-01 open Assets:Checking\n"
            "2024-01-01 open Assets:Investment:BrokerageA\n"
            "    block-transactions: TRUE\n"
            "2024-01-01 open Assets:Investment:BrokerageB\n"
            "    block-transactions: TRUE\n"
            "\n"
            '2024-02-01 * "Two blocked"\n'
            "    Assets:Investment:BrokerageA  10 USD\n"
            "    Assets:Investment:BrokerageB  10 USD\n"
            "    Assets:Checking              -20 USD\n"
        )
        _, errors, _ = loader.load_string(ledger)
        block_errors = _block_errors(errors)
        assert len(block_errors) == 2
        messages = " ".join(e.message for e in block_errors)
        assert "BrokerageA" in messages
        assert "BrokerageB" in messages
