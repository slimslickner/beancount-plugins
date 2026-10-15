"""Integration tests for all beancount plugins using a shared sample ledger."""

from pathlib import Path

import pytest
from beancount import loader
from beancount.core import data

from beancount_plugins.check_valid_metadata import (
    _account_pattern_matches,
    _compile_spec,
    _entry_accounts,
    check_valid_metadata,
)

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


# ---------------------------------------------------------------------------
# promote_account_metadata plugin
# ---------------------------------------------------------------------------


class TestPromoteAccountMetadata:
    def test_metadata_promoted_to_matching_posting(self, transactions):
        """tax-treatment from Open directive should appear on the matching posting."""
        txn = _find_txn(transactions, "Tax withholding")
        posting = _find_posting(txn, "Expenses:TaxWithheld")
        assert (
            posting.meta is not None and posting.meta.get("tax-treatment") == "pre-tax"
        )

    def test_metadata_not_on_other_posting_in_same_txn(self, transactions):
        """Checking posting in the same txn should not receive tax-treatment."""
        txn = _find_txn(transactions, "Tax withholding")
        posting = _find_posting(txn, "Assets:Checking")
        assert posting.meta is None or "tax-treatment" not in posting.meta

    def test_account_without_open_metadata_unaffected(self, transactions):
        """Posting to an account with no Open metadata should be unchanged."""
        txn = _find_txn(transactions, "General no-meta expense")
        posting = _find_posting(txn, "Expenses:NoMeta")
        assert posting.meta is None or "tax-treatment" not in posting.meta


# ---------------------------------------------------------------------------
# transfer_remove_payee plugin
# ---------------------------------------------------------------------------


class TestTransferRemovePayee:
    def test_transfer_with_payee_errors(self, error_messages):
        """Transfer with payee and distinct immediate parents produces an error."""
        assert any(
            "Transfer transaction has a payee" in m and "Transfer to brokerage" in m
            for m in error_messages
        )

    def test_pure_transfer_no_error(self, error_messages):
        """Pure transfer (siblings, no payee) produces no error."""
        assert not any(
            "Transfer transaction has a payee" in m and "Move to savings" in m
            for m in error_messages
        )

    def test_transfer_same_parent_no_error(self, error_messages):
        """Checking<->Savings (same parent) with a payee is not flagged."""
        assert not any(
            "Transfer transaction has a payee" in m and "Bank A" in m
            for m in error_messages
        )

    def test_mixed_transfer_and_expense_no_error(self, error_messages):
        """Transaction mixing transfer and Expenses: produces no error."""
        assert not any(
            "Transfer transaction has a payee" in m and "Refund issued" in m
            for m in error_messages
        )

    def test_receivable_with_payee_no_error(self, error_messages):
        """Assets:Receivable: with a payee is excluded (AR uses payees for invoices)."""
        assert not any(
            "Transfer transaction has a payee" in m and "Invoice payment" in m
            for m in error_messages
        )


# ---------------------------------------------------------------------------
# missing_contribution_year plugin
# ---------------------------------------------------------------------------


class TestMissingContributionYear:
    def test_default_hsa_counterparty_errors(self, error_messages):
        """HSA + default counterparty, no contribution-year → error."""
        assert any(
            "missing 'contribution-year'" in m
            and "HSA contribution from matched transfer" in m
            for m in error_messages
        )

    def test_existing_contribution_year_no_error(self, error_messages):
        """contribution-year on the destination posting → no error."""
        assert not any(
            "missing 'contribution-year'" in m
            and "HSA contribution with year on posting" in m
            for m in error_messages
        )

    def test_contribution_year_on_transaction_errors(self, error_messages):
        """contribution-year on the transaction (wrong place) still errors."""
        assert any(
            "missing 'contribution-year'" in m
            and "HSA contribution with year on txn" in m
            for m in error_messages
        )

    def test_hsa_no_counterparty_no_error(self, error_messages):
        """HSA + random asset (not in counterparty list) → no error."""
        assert not any(
            "missing 'contribution-year'" in m and "HSA move from checking" in m
            for m in error_messages
        )

    def test_401k_employer_contribution_errors(self, error_messages):
        """401k + employer contribution, no contribution-year → error."""
        assert any(
            "missing 'contribution-year'" in m and "401k employer match" in m
            for m in error_messages
        )

    def test_ira_no_counterparty_no_error(self, error_messages):
        """IRA + random asset (not in counterparty list) → no error."""
        assert not any(
            "missing 'contribution-year'" in m and "IRA rebalance" in m
            for m in error_messages
        )


def test_check_valid_metadata_missing_config(tmp_path):
    """Missing metadata schema file should produce a descriptive error."""
    from beancount_plugins.check_valid_metadata import check_valid_metadata

    options_map = {"filename": str(tmp_path / "test.beancount")}
    _, errors = check_valid_metadata([], options_map, config="nonexistent.yaml")
    assert any("not found" in e.message for e in errors)


# ---------------------------------------------------------------------------
# account_pattern (scoped required metadata)
# ---------------------------------------------------------------------------


class TestPostingAccountPatternReceipt:
    """account_pattern on posting-level required fields.

    receipt_id is required only on postings to "Expenses:Reimbursable", and
    is rejected on postings that don't match the pattern.
    """

    def test_pattern_match_triggers_requirement(self, error_messages):
        """receipt_id must be present when the posting matches the account_pattern."""
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
        """No receipt_id error when field is provided on the matching posting."""
        count = sum(
            1 for m in error_messages if "Missing required metadata 'receipt_id'" in m
        )
        assert count == 1  # would be 2 if the satisfied transaction also fired

    def test_present_on_non_matching_posting_errors(self, error_messages):
        """receipt_id on Expenses:Travel (non-matching) is not allowed."""
        assert any(
            "Metadata 'receipt_id'" in m
            and "only allowed on accounts matching" in m
            and "Expenses:Travel" in m
            for m in error_messages
        )


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

    def test_present_on_non_matching_account_errors(self, error_messages):
        """tax-account-type on Expenses:MisplacedMeta is not allowed."""
        assert any(
            "Metadata 'tax-account-type'" in m
            and "only allowed on accounts matching" in m
            and "Expenses:MisplacedMeta" in m
            for m in error_messages
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


class TestAccountPatternPrefixMatch:
    """account_pattern should match from the start of the account name.

    A pattern like "^(Assets|Liabilities|...)" must apply to nested accounts
    (e.g., Assets:Investment:Retirement:...), not only exact root names.
    """

    def test_prefix_open_pattern_requires_label(self, tmp_path):
        """A deeply nested Assets account missing 'label' should produce an error."""
        schema = tmp_path / "metadata_schema.yaml"
        schema.write_text(
            "metadata:\n"
            "  open:\n"
            "    label:\n"
            "      type: string\n"
            "      required: true\n"
            '      account_pattern: "^(Assets|Liabilities|Equity|Income|Expenses)"\n'
        )
        ledger = tmp_path / "test.beancount"
        ledger.write_text(
            'option "title" "Prefix pattern test"\n'
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.check_valid_metadata" "metadata_schema.yaml"\n'
            "\n"
            '2024-01-01 open Assets:Investment:Retirement:Mattis-Fidelity-Roth-IRA:FXAIX FXAIX "FIFO"\n'
            "  fava-uptodate-indication: TRUE\n"
            '  account-owner: "matti"\n'
            '  tax-account-type: "roth"\n'
        )
        _, errors, _ = loader.load_file(str(ledger))
        assert any("Missing required metadata 'label'" in e.message for e in errors)

    def test_non_matching_root_account_no_label_error(self, tmp_path):
        """An account that does not match the prefix should not require label."""
        schema = tmp_path / "metadata_schema.yaml"
        schema.write_text(
            "metadata:\n"
            "  open:\n"
            "    label:\n"
            "      type: string\n"
            "      required: true\n"
            '      account_pattern: "^(Assets|Liabilities|Equity|Income|Expenses)"\n'
        )
        ledger = tmp_path / "test.beancount"
        ledger.write_text(
            'option "title" "Prefix pattern test"\n'
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.check_valid_metadata" "metadata_schema.yaml"\n'
            "\n"
            "2024-01-01 open Foo:Bar USD\n"
        )
        _, errors, _ = loader.load_file(str(ledger))
        assert not any("Missing required metadata 'label'" in e.message for e in errors)


class TestAccountPatternBoundary:
    """Unit tests for account_pattern matching semantics."""

    def test_prefix_matches_subaccounts(self):
        """A root prefix should match itself and any nested account."""
        spec = {"required": True, "account_pattern": "Expenses"}
        compiled = _compile_spec(spec)
        assert _account_pattern_matches(compiled, ["Expenses:Groceries"])
        assert _account_pattern_matches(compiled, ["Expenses"])
        assert not _account_pattern_matches(compiled, ["ExpensesChase"])

    def test_wildcard_pattern_still_works(self):
        """A colon + wildcard pattern should match any account under that prefix."""
        spec = {"required": True, "account_pattern": "Expenses:.*"}
        compiled = _compile_spec(spec)
        assert _account_pattern_matches(compiled, ["Expenses:Groceries"])
        assert _account_pattern_matches(compiled, ["Expenses:Reimbursable:Client"])
        assert not _account_pattern_matches(compiled, ["Income:Salary"])

    def test_alternation_respects_component_boundaries(self):
        """Alternations must match whole components, not partial names."""
        spec = {"required": True, "account_pattern": "^(Expenses|Liabilities:Loans)"}
        compiled = _compile_spec(spec)
        assert _account_pattern_matches(compiled, ["Expenses"])
        assert _account_pattern_matches(compiled, ["Expenses:Groceries"])
        assert _account_pattern_matches(compiled, ["Liabilities:Loans"])
        assert _account_pattern_matches(compiled, ["Liabilities:Loans:Chase"])
        assert not _account_pattern_matches(compiled, ["Liabilities:LoansChase"])

    def test_pattern_ending_with_colon_matches_subaccounts(self):
        """A pattern consuming the trailing ':' is still a whole-component match."""
        spec = {"required": True, "account_pattern": "^Expenses:"}
        compiled = _compile_spec(spec)
        assert _account_pattern_matches(compiled, ["Expenses:Groceries"])
        assert not _account_pattern_matches(compiled, ["Expenses"])
        assert not _account_pattern_matches(compiled, ["ExpensesChase"])

    def test_negative_lookahead_pattern(self):
        """'^Assets:(?!Property:)' should match Assets subaccounts except Property."""
        spec = {"required": True, "account_pattern": "^Assets:(?!Property:)"}
        compiled = _compile_spec(spec)
        assert _account_pattern_matches(
            compiled, ["Assets:Investment:Brokerage:Fidelity-Brokerage:Cash"]
        )
        assert _account_pattern_matches(compiled, ["Assets:Checking"])
        assert not _account_pattern_matches(compiled, ["Assets:Property:House"])
        assert not _account_pattern_matches(compiled, ["Liabilities:CreditCard"])


class TestAccountPatternScope:
    """account_pattern restricts a field to matching accounts (open/close/document/note)."""

    def _load(self, tmp_path, schema_body, ledger_body):
        schema = tmp_path / "metadata_schema.yaml"
        schema.write_text(schema_body)
        ledger = tmp_path / "test.beancount"
        ledger.write_text(
            'option "title" "Scope test"\n'
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.check_valid_metadata" "metadata_schema.yaml"\n'
            "\n" + ledger_body
        )
        _, errors, _ = loader.load_file(str(ledger))
        return [e.message for e in errors]

    def test_open_matching_account_allowed(self, tmp_path):
        """A patterned field on a matching Open account is accepted."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  open:\n"
            "    code:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            '2024-01-01 open Assets:Investment:Brokerage\n  code: "BRK"\n',
        )
        assert not any("only allowed on accounts matching" in m for m in messages)

    def test_open_non_matching_account_rejected(self, tmp_path):
        """A patterned field on a non-matching Open account errors."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  open:\n"
            "    code:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            '2024-01-01 open Expenses:Groceries\n  code: "BRK"\n',
        )
        assert any(
            "Metadata 'code'" in m
            and "only allowed on accounts matching" in m
            and "Expenses:Groceries" in m
            for m in messages
        )

    def test_optional_pattern_still_restricts(self, tmp_path):
        """required: false only controls presence, not where the field may appear."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  open:\n"
            "    code:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            '2024-01-01 open Expenses:Groceries\n  code: "BRK"\n',
        )
        assert any("only allowed on accounts matching" in m for m in messages)

    def test_close_non_matching_account_rejected(self, tmp_path):
        """A patterned field on a non-matching Close account errors."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  close:\n"
            "    reason:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Liabilities"\n',
            "2024-01-01 open Expenses:Groceries\n"
            "2024-12-31 close Expenses:Groceries\n"
            '  reason: "done"\n',
        )
        assert any(
            "Metadata 'reason'" in m
            and "only allowed on accounts matching" in m
            and "Expenses:Groceries" in m
            for m in messages
        )

    def test_document_matching_account_allowed(self, tmp_path):
        """A patterned field on a matching Document account is accepted."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  document:\n"
            "    verified:\n"
            "      type: bool\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            "2024-01-01 open Assets:Investment:Brokerage\n"
            '2024-02-01 document Assets:Investment:Brokerage "/tmp/stmt.pdf"\n'
            "  verified: TRUE\n",
        )
        assert not any("only allowed on accounts matching" in m for m in messages)

    def test_note_non_matching_account_rejected(self, tmp_path):
        """A patterned field on a non-matching Note account errors."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  note:\n"
            "    importance:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            "2024-01-01 open Expenses:Groceries\n"
            '2024-03-01 note Expenses:Groceries "why"\n'
            '  importance: "high"\n',
        )
        assert any(
            "Metadata 'importance'" in m
            and "only allowed on accounts matching" in m
            and "Expenses:Groceries" in m
            for m in messages
        )


class TestAccountPatternConfigErrors:
    """account_pattern on non-account-scoped sections is a load-time config error."""

    def _messages(self, tmp_path, dtype):
        schema = tmp_path / "metadata_schema.yaml"
        schema.write_text(
            "metadata:\n"
            f"  {dtype}:\n"
            "    foo:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets"\n'
        )
        options_map = {"filename": str(tmp_path / "test.beancount")}
        _, errors = check_valid_metadata([], options_map, config="metadata_schema.yaml")
        return [e.message for e in errors]

    @pytest.mark.parametrize("dtype", ["transaction", "event", "commodity"])
    def test_pattern_disallowed_section(self, tmp_path, dtype):
        assert any(
            f"account_pattern is not valid on '{dtype}' metadata 'foo'" in m
            for m in self._messages(tmp_path, dtype)
        )

    @pytest.mark.parametrize("dtype", ["posting", "open", "close", "document", "note"])
    def test_pattern_allowed_section(self, tmp_path, dtype):
        # A declared-but-unused key also errors (entries is empty here), so
        # assert specifically that account_pattern is accepted as a config key.
        assert not any(
            "account_pattern is not valid" in m for m in self._messages(tmp_path, dtype)
        )


class TestUnusedMetadataKeys:
    """Declared-but-unused schema keys are reported as errors."""

    def _load(self, tmp_path, schema_body, ledger_body=""):
        schema = tmp_path / "metadata_schema.yaml"
        schema.write_text(schema_body)
        ledger = tmp_path / "test.beancount"
        ledger.write_text(
            'option "title" "Unused key test"\n'
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.check_valid_metadata" "metadata_schema.yaml"\n'
            "\n" + ledger_body
        )
        _, errors, _ = loader.load_file(str(ledger))
        return [e.message for e in errors]

    def test_unused_transaction_key_errors(self, tmp_path):
        """A transaction key that never appears is flagged as unused."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  transaction:\n"
            "    never_used:\n"
            "      type: string\n"
            "      required: false\n",
        )
        assert any(
            "Declared metadata key 'never_used' in 'transaction' schema is never used"
            in m
            for m in messages
        )

    def test_used_transaction_key_passes(self, tmp_path):
        """A transaction key that appears on a directive is not flagged."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  transaction:\n"
            "    used_key:\n"
            "      type: string\n"
            "      required: false\n",
            '2024-01-01 * "x"\n'
            '    used_key: "v"\n'
            "    Expenses:Travel  1.00 USD\n"
            "    Assets:Checking  -1.00 USD\n",
        )
        assert not any("never used" in m for m in messages)

    def test_unused_open_key_errors(self, tmp_path):
        """An Open key that never appears is flagged as unused."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  open:\n"
            "    never_used:\n"
            "      type: string\n"
            "      required: false\n",
            "2024-01-01 open Assets:Checking\n",
        )
        assert any(
            "Declared metadata key 'never_used' in 'open' schema is never used" in m
            for m in messages
        )

    def test_posting_key_used_on_posting_passes(self, tmp_path):
        """A posting key that appears on a posting is not flagged."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  posting:\n"
            "    cost_center:\n"
            "      type: string\n"
            "      required: false\n",
            '2024-01-01 * "x"\n'
            "    Expenses:Travel  1.00 USD\n"
            '        cost_center: "ops"\n'
            "    Assets:Checking  -1.00 USD\n",
        )
        assert not any("never used" in m for m in messages)

    def test_pattern_key_matching_usage_counts(self, tmp_path):
        """A patterned key used on a matching account is not flagged."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  open:\n"
            "    code:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            '2024-01-01 open Assets:Investment:Brokerage\n  code: "BRK"\n',
        )
        assert not any("never used" in m for m in messages)

    def test_pattern_key_non_matching_only_is_unused(self, tmp_path):
        """A patterned key seen only on a non-matching account is still unused."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  open:\n"
            "    code:\n"
            "      type: string\n"
            "      required: false\n"
            '      account_pattern: "Assets:Investment"\n',
            '2024-01-01 open Expenses:Groceries\n  code: "BRK"\n',
        )
        assert any(
            "Declared metadata key 'code' in 'open' schema is never used" in m
            for m in messages
        )
        # The non-matching occurrence is independently rejected.
        assert any("only allowed on accounts matching" in m for m in messages)

    def test_declared_key_also_in_exceptions_is_used(self, tmp_path):
        """A declared key listed in plugin_exceptions still counts as used."""
        messages = self._load(
            tmp_path,
            "metadata:\n"
            "  transaction:\n"
            "    used_key:\n"
            "      type: string\n"
            "      required: false\n"
            "  plugin_exceptions:\n"
            "    - allowed_keys: [used_key]\n",
            '2024-01-01 * "x"\n'
            '    used_key: "v"\n'
            "    Expenses:Travel  1.00 USD\n"
            "    Assets:Checking  -1.00 USD\n",
        )
        assert not any("never used" in m for m in messages)

    def test_unused_key_anchored_to_ledger_file(self, tmp_path):
        """The error points at the ledger file (line 0), not the schema file."""
        schema = tmp_path / "metadata_schema.yaml"
        schema.write_text(
            "metadata:\n"
            "  transaction:\n"
            "    never_used:\n"
            "      type: string\n"
            "      required: false\n"
        )
        ledger = tmp_path / "test.beancount"
        ledger.write_text(
            'option "title" "Anchor test"\n'
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.check_valid_metadata" "metadata_schema.yaml"\n'
            "\n"
        )
        _, errors, _ = loader.load_file(str(ledger))
        unused = [e for e in errors if "never used" in e.message]
        assert unused
        assert unused[0].source["filename"] == str(ledger)
        assert unused[0].source["lineno"] == 0


class TestEntryAccounts:
    """Unit tests for _entry_accounts."""

    def test_transaction_returns_posting_accounts(self):
        txn = data.Transaction(
            meta={},
            date=None,
            flag="*",
            payee=None,
            narration="x",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting("Assets:Checking", None, None, None, None, None),
                data.Posting("Expenses:Groceries", None, None, None, None, None),
            ],
        )
        assert _entry_accounts(txn) == ["Assets:Checking", "Expenses:Groceries"]

    def test_account_scoped_directives(self):
        open_entry = data.Open(
            meta={}, date=None, account="Assets:Checking", currencies=None, booking=None
        )
        assert _entry_accounts(open_entry) == ["Assets:Checking"]

    def test_accountless_directive(self):
        event = data.Event(meta={}, date=None, type="x", description="y")
        assert _entry_accounts(event) == []


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
