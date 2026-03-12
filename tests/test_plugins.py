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

    def test_non_string_tags_error(self, error_messages):
        """Posting 'tags' with a non-string value should produce an error."""
        assert any("must be a string" in m for m in error_messages)


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
# check_missing_links plugin
# ---------------------------------------------------------------------------


class TestCheckMissingLinks:
    def test_linked_transaction_passes(self, error_messages):
        """A linked transaction to a link-required account should not error."""
        assert not any(
            "Invoice payment received" in m and "missing link" in m
            for m in error_messages
        )

    def test_unlinked_ar_error(self, error_messages):
        """Unlinked transaction posting to link-required Assets:AccountsReceivable."""
        assert any(
            "Assets:AccountsReceivable" in m and "missing link" in m
            for m in error_messages
        )

    def test_non_link_required_account_no_error(self, error_messages):
        """Transaction to non-link-required Income:Salary should not error."""
        assert not any(
            "Income:Salary" in m and "missing link" in m for m in error_messages
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


def test_check_valid_tags_missing_config(tmp_path):
    """Missing tags config file should produce a descriptive error."""
    from beancount_plugins.check_valid_tags import check_valid_tags

    options_map = {"filename": str(tmp_path / "test.beancount")}
    _, errors = check_valid_tags([], options_map, config="nonexistent.yaml")
    assert any("not found" in e.message for e in errors)


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

    def test_pattern_constraint_violation(self, error_messages):
        """ref_code value not matching pattern should produce a format error."""
        assert any(
            "does not match pattern" in m and "ref_code" in m for m in error_messages
        )

    def test_pattern_constraint_valid_passes(self, error_messages):
        """ref_code matching pattern REF-123 should not error."""
        assert not any("REF-123" in m for m in error_messages)

    def test_type_constraint_violation(self, error_messages):
        """is_billable set to a string instead of bool should produce a type error."""
        assert any("Invalid type" in m and "is_billable" in m for m in error_messages)


def test_check_valid_metadata_missing_config(tmp_path):
    """Missing metadata schema file should produce a descriptive error."""
    from beancount_plugins.check_valid_metadata import check_valid_metadata

    options_map = {"filename": str(tmp_path / "test.beancount")}
    _, errors = check_valid_metadata([], options_map, config="nonexistent.yaml")
    assert any("not found" in e.message for e in errors)


# ---------------------------------------------------------------------------
# account_pattern (scoped required metadata)
# ---------------------------------------------------------------------------


class TestTransactionAccountPattern:
    """account_pattern on transaction-level required fields.

    receipt_id is required only when a posting matches "Expenses:Reimbursable".
    """

    def test_pattern_match_triggers_requirement(self, error_messages):
        """receipt_id must be present when any posting matches the account_pattern."""
        assert any(
            "Missing required metadata 'receipt_id'" in m for m in error_messages
        )

    def test_only_one_receipt_id_error(self, error_messages):
        """Exactly one receipt_id error: only the missing-receipt transaction fires."""
        count = sum(
            1 for m in error_messages if "Missing required metadata 'receipt_id'" in m
        )
        assert count == 1

    def test_satisfied_pattern_no_error(self, error_messages):
        """No receipt_id error when field is provided on the matching transaction."""
        count = sum(
            1 for m in error_messages if "Missing required metadata 'receipt_id'" in m
        )
        assert count == 1  # would be 2 if the satisfied transaction also fired


class TestOpenAccountPattern:
    """account_pattern on Open directive required fields.

    tax-account-type is required only on accounts matching "Assets:Investment.*".
    """

    def test_missing_field_triggers_error(self, error_messages):
        """tax-account-type missing on Assets:Investment:Brokerage should error."""
        assert any(
            "Missing required metadata 'tax-account-type'" in m for m in error_messages
        )

    def test_only_one_error(self, error_messages):
        """Exactly one error: Brokerage is missing it; IRA provides it; Checking doesn't match."""
        count = sum(
            1
            for m in error_messages
            if "Missing required metadata 'tax-account-type'" in m
        )
        assert count == 1

    def test_satisfied_open_no_error(self, error_messages):
        """Assets:Investment:IRA with tax-account-type provided should not error."""
        # Verified indirectly: count == 1 means IRA (provided) didn't fire.
        count = sum(
            1
            for m in error_messages
            if "Missing required metadata 'tax-account-type'" in m
        )
        assert count == 1

    def test_non_matching_account_no_error(self, error_messages):
        """Assets:Checking doesn't match account_pattern, no error expected."""
        assert not any(
            "tax-account-type" in m and "Checking" in m for m in error_messages
        )


class TestPostingAccountPattern:
    """account_pattern on posting-level required fields.

    cost_center is required only on postings to "Expenses:Billable".
    """

    def test_missing_cost_center_error(self, error_messages):
        """Posting to Expenses:Billable without cost_center should error."""
        assert any(
            "Missing required metadata 'cost_center'" in m for m in error_messages
        )

    def test_only_one_cost_center_error(self, error_messages):
        """Exactly one error: only the posting without cost_center fires."""
        count = sum(
            1 for m in error_messages if "Missing required metadata 'cost_center'" in m
        )
        assert count == 1

    def test_satisfied_posting_no_error(self, error_messages):
        """Posting to Expenses:Billable with cost_center provided should not error."""
        count = sum(
            1 for m in error_messages if "Missing required metadata 'cost_center'" in m
        )
        assert count == 1  # would be 2 if the satisfied posting also fired


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
