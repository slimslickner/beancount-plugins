"""Unit tests for promote_account_metadata plugin."""

import logging

from beancount import loader
from beancount.core import data

from beancount_plugins.promote_account_metadata import _parse_config


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_parse_config_none():
    whitelist, blacklist, errors = _parse_config(None)
    assert whitelist is None
    assert blacklist is None
    assert errors == []


def test_parse_config_empty_string():
    whitelist, blacklist, errors = _parse_config("")
    assert whitelist is None
    assert blacklist is None
    assert errors == []


def test_parse_config_whitelist_list():
    whitelist, blacklist, errors = _parse_config("{'whitelist': ['tax-treatment']}")
    assert whitelist == {"tax-treatment"}
    assert blacklist is None
    assert errors == []


def test_parse_config_whitelist_string():
    whitelist, blacklist, errors = _parse_config("{'whitelist': 'tax-treatment'}")
    assert whitelist == {"tax-treatment"}
    assert blacklist is None
    assert errors == []


def test_parse_config_blacklist_list():
    whitelist, blacklist, errors = _parse_config("{'blacklist': ['tag-expected']}")
    assert whitelist is None
    assert blacklist == {"tag-expected"}
    assert errors == []


def test_parse_config_blacklist_string():
    whitelist, blacklist, errors = _parse_config("{'blacklist': 'tag-expected'}")
    assert whitelist is None
    assert blacklist == {"tag-expected"}
    assert errors == []


def test_parse_config_both_whitelist_wins():
    whitelist, blacklist, errors = _parse_config(
        "{'whitelist': ['a'], 'blacklist': ['b']}"
    )
    assert whitelist == {"a"}
    assert blacklist is None
    assert errors == []


def test_parse_config_multiline():
    config = "{\n    'whitelist': 'tax-treatment'\n}"
    whitelist, blacklist, errors = _parse_config(config)
    assert whitelist == {"tax-treatment"}
    assert errors == []


def test_parse_config_invalid_syntax():
    whitelist, blacklist, errors = _parse_config("not valid python")
    assert whitelist is None
    assert blacklist is None
    assert len(errors) == 1
    assert "Invalid config" in errors[0].message


def test_parse_config_unknown_keys():
    whitelist, blacklist, errors = _parse_config("{'unknown_key': []}")
    assert len(errors) == 1
    assert "unknown_key" in errors[0].message


# ---------------------------------------------------------------------------
# Promotion behavior
# ---------------------------------------------------------------------------

_BASIC_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.promote_account_metadata"

2026-01-01 open Assets:Checking USD
2026-01-01 open Expenses:Federal USD
  tax-treatment: "pre-tax"
2026-01-01 open Expenses:Regular USD

2026-01-02 * "Paycheck"
  Expenses:Federal  200 USD
  Assets:Checking  -200 USD

2026-01-02 * "Rent"
  Expenses:Regular  1000 USD
  Assets:Checking  -1000 USD
"""

_CONFLICT_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.promote_account_metadata"

2026-01-01 open Assets:Checking USD
2026-01-01 open Expenses:Federal USD
  tax-treatment: "pre-tax"

2026-01-02 * "Conflict"
  Expenses:Federal  200 USD
    tax-treatment: "post-tax"
  Assets:Checking  -200 USD
"""

_MULTI_KEY_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.promote_account_metadata"{config}

2026-01-01 open Assets:Checking USD
2026-01-01 open Expenses:Work USD
  tax-treatment: "pre-tax"
  cost-center: "engineering"
  internal-note: "ignore-me"

2026-01-02 * "Work expense"
  Expenses:Work  100 USD
  Assets:Checking  -100 USD
"""


def _find_txn(entries, narration):
    return next(
        e
        for e in entries
        if isinstance(e, data.Transaction) and e.narration == narration
    )


def _find_posting(txn, account):
    return next(p for p in txn.postings if p.account == account)


class TestPromoteBasic:
    def test_metadata_promoted_to_matching_posting(self):
        entries, _, _ = loader.load_string(_BASIC_LEDGER)
        txn = _find_txn(entries, "Paycheck")
        posting = _find_posting(txn, "Expenses:Federal")
        assert posting.meta.get("tax-treatment") == "pre-tax"

    def test_metadata_not_on_other_posting_in_same_txn(self):
        entries, _, _ = loader.load_string(_BASIC_LEDGER)
        txn = _find_txn(entries, "Paycheck")
        posting = _find_posting(txn, "Assets:Checking")
        assert "tax-treatment" not in posting.meta

    def test_account_without_open_metadata_unaffected(self):
        entries, _, _ = loader.load_string(_BASIC_LEDGER)
        txn = _find_txn(entries, "Rent")
        posting = _find_posting(txn, "Expenses:Regular")
        assert "tax-treatment" not in posting.meta

    def test_no_plugin_errors_on_valid_ledger(self):
        _, errors, _ = loader.load_string(_BASIC_LEDGER)
        plugin_errors = [e for e in errors if "promote_account_metadata" in e.message]
        assert plugin_errors == []


class TestConflict:
    def test_posting_value_wins(self):
        entries, _, _ = loader.load_string(_CONFLICT_LEDGER)
        txn = _find_txn(entries, "Conflict")
        posting = _find_posting(txn, "Expenses:Federal")
        assert posting.meta.get("tax-treatment") == "post-tax"

    def test_conflict_logs_warning(self, caplog):
        with caplog.at_level(
            logging.WARNING,
            logger="beancount_plugins.promote_account_metadata",
        ):
            loader.load_string(_CONFLICT_LEDGER)
        assert any("conflict" in r.message.lower() for r in caplog.records)


class TestFilters:
    def test_no_config_promotes_all_keys(self):
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=""))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert posting.meta.get("cost-center") == "engineering"
        assert posting.meta.get("internal-note") == "ignore-me"

    def test_whitelist_only_promotes_listed_keys(self):
        config = " \"{'whitelist': 'tax-treatment'}\""
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=config))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert "cost-center" not in posting.meta
        assert "internal-note" not in posting.meta

    def test_blacklist_excludes_listed_keys(self):
        config = " \"{'blacklist': 'internal-note'}\""
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=config))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert posting.meta.get("cost-center") == "engineering"
        assert "internal-note" not in posting.meta

    def test_whitelist_wins_when_both_provided(self):
        config = " \"{'whitelist': 'tax-treatment', 'blacklist': 'tax-treatment'}\""
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=config))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert "cost-center" not in posting.meta
