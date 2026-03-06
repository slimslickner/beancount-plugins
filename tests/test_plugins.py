"""Integration tests for all beancount plugins using a shared sample ledger."""

from pathlib import Path

import pytest
from beancount import loader
from beancount.core import data

SAMPLE_LEDGER = Path(__file__).parent / "sample.beancount"


@pytest.fixture(scope="module")
def ledger():
    """Load the sample ledger once for all tests."""
    entries, errors, options_map = loader.load_file(str(SAMPLE_LEDGER))
    return entries, errors, options_map


@pytest.fixture(scope="module")
def transactions(ledger):
    entries, _, _ = ledger
    return [e for e in entries if isinstance(e, data.Transaction)]


@pytest.fixture(scope="module")
def error_messages(ledger):
    _, errors, _ = ledger
    return [e.message for e in errors]


# ---------------------------------------------------------------------------
# posting_tags plugin
# ---------------------------------------------------------------------------


class TestPostingTags:
    def test_posting_tags_promoted_to_transaction(self, transactions):
        """Posting-level tags: 'personal' should be promoted to transaction tags."""
        txn = _find_txn(transactions, "Split purchase")
        assert "personal" in txn.tags
        assert "business" in txn.tags

    def test_posting_tags_metadata_preserved(self, transactions):
        """Posting metadata 'tags' should still be present after promotion."""
        txn = _find_txn(transactions, "Split purchase")
        groceries = _find_posting(txn, "Expenses:Groceries")
        assert groceries.meta is not None and groceries.meta["tags"] == "personal"


# ---------------------------------------------------------------------------
# check_missing_tags plugin
# ---------------------------------------------------------------------------


class TestCheckMissingTags:
    def test_tagged_transaction_passes(self, error_messages):
        """A tagged transaction to a tag-required account should not error."""
        assert not any(
            "Grocery store" in m and "missing tags" in m for m in error_messages
        )

    def test_untagged_groceries_error(self, error_messages):
        """Untagged transaction posting to tag-required Expenses:Groceries."""
        assert any(
            "Expenses:Groceries" in m and "missing tags" in m for m in error_messages
        )

    def test_untagged_credit_card_error(self, error_messages):
        """Untagged transaction posting to tag-required Liabilities:CreditCard."""
        assert any(
            "Liabilities:CreditCard" in m and "missing tags" in m
            for m in error_messages
        )

    def test_non_tag_required_account_no_error(self, error_messages):
        """Transaction to non-tag-required Expenses:Rent should not error."""
        assert not any(
            "Expenses:Rent" in m and "missing tags" in m for m in error_messages
        )


# ---------------------------------------------------------------------------
# check_valid_tags plugin
# ---------------------------------------------------------------------------


class TestCheckValidTags:
    def test_valid_tag_passes(self, error_messages):
        """Known tag #personal should not produce an error."""
        assert not any("Undefined tag '#personal'" in m for m in error_messages)

    def test_undefined_tag_error(self, error_messages):
        """Unknown tag #nonexistent-tag should produce an error."""
        assert any("Undefined tag '#nonexistent-tag'" in m for m in error_messages)

    def test_require_link_with_link_passes(self, error_messages):
        """#reimbursable with ^receipt-001 should not error."""
        # The "Business dinner" txn has both #reimbursable and ^receipt-001
        assert not any(
            "requires a link" in m and "Business dinner" in m for m in error_messages
        )

    def test_require_link_without_link_errors(self, error_messages):
        """#reimbursable without a link should produce an error."""
        assert any("'#reimbursable' requires a link" in m for m in error_messages)


# ---------------------------------------------------------------------------
# check_valid_metadata plugin
# ---------------------------------------------------------------------------


class TestCheckValidMetadata:
    def test_valid_metadata_passes(self, error_messages):
        """source_payee on a transaction should not error."""
        assert not any("source_payee" in m and "Invalid" in m for m in error_messages)

    def test_unknown_posting_key_error(self, error_messages):
        """Unknown posting metadata key 'unknown_key' should error."""
        assert any(
            "unknown_key" in m and "Invalid metadata key" in m for m in error_messages
        )

    def test_invalid_allowed_values_error(self, error_messages):
        """Posting tag value 'invalid-category' should error."""
        assert any("invalid-category" in m for m in error_messages)

    def test_unknown_transaction_key_error(self, error_messages):
        """Unknown transaction metadata key 'bogus_field' should error."""
        assert any(
            "bogus_field" in m and "Invalid metadata key" in m for m in error_messages
        )


# ---------------------------------------------------------------------------
# account_pattern (scoped required metadata)
# ---------------------------------------------------------------------------


class TestAccountPattern:
    """Test account_pattern scoping for required metadata fields.

    The schema (tests/metadata_schema.yaml) declares receipt_id as required
    with account_pattern "Expenses:Reimbursable". Three transactions in
    sample.beancount exercise this:
      - "Reimbursable missing receipt": posts to Expenses:Reimbursable, no receipt_id → ERROR
      - "Assets transfer": posts only to Assets → NO ERROR
      - "Reimbursable with receipt": posts to Expenses:Reimbursable, receipt_id provided → NO ERROR
      - "Travel no receipt needed": posts to Expenses:Travel (pattern is exact, no match) → NO ERROR
    """

    def test_pattern_match_triggers_requirement(self, error_messages):
        """receipt_id must be present when any posting matches the account_pattern."""
        assert any(
            "Missing required metadata 'receipt_id'" in m for m in error_messages
        )

    def test_only_one_receipt_id_error(self, error_messages):
        """Exactly one receipt_id error: only the missing-receipt transaction fires.

        This proves that non-matching accounts (Assets, Expenses:Travel) and
        the satisfied transaction do not produce spurious errors.
        """
        count = sum(
            1 for m in error_messages if "Missing required metadata 'receipt_id'" in m
        )
        assert count == 1

    def test_satisfied_pattern_no_error(self, error_messages):
        """No receipt_id error when field is provided on the matching transaction."""
        # Verified indirectly by test_only_one_receipt_id_error — only the
        # missing-receipt transaction fires, not "Reimbursable with receipt".
        count = sum(
            1 for m in error_messages if "Missing required metadata 'receipt_id'" in m
        )
        assert count == 1  # would be 2 if the satisfied transaction also fired


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_txn(transactions: list[data.Transaction], narration: str) -> data.Transaction:
    for txn in transactions:
        if txn.narration == narration:
            return txn
    raise ValueError(f"Transaction not found: {narration}")


def _find_posting(txn: data.Transaction, account: str) -> data.Posting:
    for posting in txn.postings:
        if posting.account == account:
            return posting
    raise ValueError(f"Posting not found: {account}")
