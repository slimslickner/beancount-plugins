"""Unit tests for missing_contribution_year plugin."""

from beancount import loader
from beancount.core import data

from beancount_plugins.missing_contribution_year import (
    _DEFAULT_COUNTERPARTY_ACCOUNTS,
    _DEFAULT_DESTINATION_ACCOUNTS,
    _DEFAULT_DESTINATION_PATTERNS,
    _parse_config,
    missing_contribution_year,
)


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def _unpack(result):
    """Unpack the 4-tuple from _parse_config."""
    dest_accts, dest_patterns, cp, errors = result
    return dest_accts, dest_patterns, cp, errors


def test_parse_config_none():
    da, dp, cp, errors = _unpack(_parse_config(None))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert errors == []


def test_parse_config_empty_string():
    da, dp, cp, errors = _unpack(_parse_config(""))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert errors == []


def test_parse_config_override_destination_accounts():
    da, dp, cp, errors = _unpack(
        _parse_config("{'destination_accounts': ['Assets:R:HSA:Cash']}")
    )
    assert da == ("Assets:R:HSA:Cash",)
    # Providing destination_accounts (non-empty) replaces default patterns.
    assert dp == ()
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert errors == []


def test_parse_config_override_destinations_patterns():
    da, dp, cp, errors = _unpack(
        _parse_config("{'destination_patterns': ['HSA', '401k']}")
    )
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == ("HSA", "401k")
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert errors == []


def test_parse_config_override_counterparties():
    da, dp, cp, errors = _unpack(
        _parse_config("{'counterparty_accounts': ['Assets:Banking:Checking']}")
    )
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == ("Assets:Banking:Checking",)
    assert errors == []


def test_parse_config_override_all_three():
    da, dp, cp, errors = _unpack(
        _parse_config(
            "{'destination_accounts': ['A:1'], "
            "'destination_patterns': ['B'], "
            "'counterparty_accounts': ['C']}"
        )
    )
    assert da == ("A:1",)
    assert dp == ("B",)
    assert cp == ("C",)
    assert errors == []


def test_parse_config_single_string_values():
    """A bare string for a list key should be normalized to a 1-tuple."""
    da, dp, cp, errors = _unpack(
        _parse_config(
            "{'destination_accounts': 'A:1', "
            "'destination_patterns': 'B', "
            "'counterparty_accounts': 'C'}"
        )
    )
    assert da == ("A:1",)
    assert dp == ("B",)
    assert cp == ("C",)
    assert errors == []


def test_parse_config_invalid_syntax():
    da, dp, cp, errors = _unpack(_parse_config("not-valid-python"))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert len(errors) == 1
    assert "Invalid config" in errors[0].message


def test_parse_config_unknown_keys():
    da, dp, cp, errors = _unpack(_parse_config("{'unknown_key': []}"))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert len(errors) == 1
    assert "unknown_key" in errors[0].message


def test_parse_config_wrong_type_destinations():
    """A non-string, non-list destination_patterns value errors."""
    da, dp, cp, errors = _unpack(_parse_config("{'destination_patterns': 42}"))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert len(errors) == 1
    assert "destination_patterns" in errors[0].message


def test_parse_config_wrong_type_destination_accounts():
    """A list containing non-strings errors."""
    da, dp, cp, errors = _unpack(_parse_config("{'destination_accounts': ['OK', 42]}"))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert len(errors) == 1
    assert "destination_accounts" in errors[0].message


def test_parse_config_wrong_type_counterparties():
    """A list containing non-strings errors."""
    da, dp, cp, errors = _unpack(_parse_config("{'counterparty_accounts': ['OK', 42]}"))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert len(errors) == 1
    assert "counterparty_accounts" in errors[0].message


def test_parse_config_not_a_dict():
    """A list or scalar at the top level is an error."""
    da, dp, cp, errors = _unpack(_parse_config("[]"))
    assert da == _DEFAULT_DESTINATION_ACCOUNTS
    assert dp == _DEFAULT_DESTINATION_PATTERNS
    assert cp == _DEFAULT_COUNTERPARTY_ACCOUNTS
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Plugin behavior — small standalone ledgers
# ---------------------------------------------------------------------------


_BASE_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.missing_contribution_year"

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Assets:Banking:Checking USD
2026-01-01 open Equity:ZeroSumMatched:Transfers USD
2026-01-01 open Income:CapTech:Employer-Contribution USD
2026-01-01 open Expenses:Groceries USD
"""


def _find_txn(entries, narration):
    return next(
        e
        for e in entries
        if isinstance(e, data.Transaction) and e.narration == narration
    )


class TestDefaultBehavior:
    """Tests that rely on the default regex destination patterns."""

    def test_default_destinations_match_hsa(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "HSA contribution"
    Assets:Retirement:HSA:Cash       1000 USD
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "HSA contribution")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_contribution_year_on_posting_skipped(self):
        """contribution-year on the destination posting → not flagged."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "HSA with year on posting"
    Assets:Retirement:HSA:Cash       1000 USD
        contribution-year: "2026"
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "HSA with year on posting")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"

    def test_contribution_year_on_transaction_still_flagged(self):
        """contribution-year on the transaction (not on the posting) is ignored."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "HSA with year on txn"
    contribution-year: "2026"
    Assets:Retirement:HSA:Cash       1000 USD
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "HSA with year on txn")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_contribution_year_on_counterparty_posting_still_flagged(self):
        """contribution-year on the wrong posting (not the destination) is ignored."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Year on the wrong posting"
    Assets:Retirement:HSA:Cash           1000 USD
    Equity:ZeroSumMatched:Transfers     -1000 USD
        contribution-year: "2026"
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Year on the wrong posting")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_non_matching_counterparty_skipped(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "HSA from random"
    Assets:Retirement:HSA:Cash   500 USD
    Assets:Banking:Checking     -500 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "HSA from random")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"

    def test_destination_not_in_default_patterns_skipped(self):
        """Account 'Assets:Retirement:CustomPlan' doesn't match HSA/401k/IRA/DC."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-01 open Assets:Retirement:CustomPlan USD
2026-01-15 * "Custom plan contribution"
    Assets:Retirement:CustomPlan   500 USD
    Equity:ZeroSumMatched:Transfers -500 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Custom plan contribution")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"

    def test_employer_contribution_flagged(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "401k employer match"
    Assets:Retirement:HSA:Cash               1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "401k employer match")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_no_destination_not_flagged(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Groceries"
    Expenses:Groceries   100 USD
    Assets:Banking:Checking -100 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Groceries")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"

    def test_no_ledger_errors(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Clean HSA"
    Assets:Retirement:HSA:Cash       1000 USD
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        _, errors, _ = loader.load_string(ledger)
        plugin_errors = [e for e in errors if "missing_contribution_year" in e.message]
        assert plugin_errors == []


class TestExactMatchOnly:
    """When destination_accounts is the only config, only listed accounts match."""

    LEDGER_TEMPLATE = (
        'option "operating_currency" "USD"\n'
        'plugin "beancount_plugins.missing_contribution_year" "{{\n'
        "    'destination_accounts': {accounts!r},\n"
        "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
        '}}"'
    )

    @staticmethod
    def _ledger(accounts):
        return (
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': " + repr(accounts) + ",\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA-old:Cash USD
2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Assets:Retirement:401k:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD

2026-01-15 * "Exact match contribution"
    Assets:Retirement:HSA:Cash               1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD

2026-01-16 * "HSA-old (not in list)"
    Assets:Retirement:HSA-old:Cash           500 USD
    Income:CapTech:Employer-Contribution     -500 USD

2026-01-17 * "401k (not in list)"
    Assets:Retirement:401k:Cash              2000 USD
    Income:CapTech:Employer-Contribution     -2000 USD
"""
        )

    def test_listed_account_flagged(self):
        entries, _, _ = loader.load_string(self._ledger(["Assets:Retirement:HSA:Cash"]))
        txn = _find_txn(entries, "Exact match contribution")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_unlisted_hsa_old_not_flagged(self):
        """HSA-old isn't in the exact list — should NOT match."""
        entries, _, _ = loader.load_string(self._ledger(["Assets:Retirement:HSA:Cash"]))
        txn = _find_txn(entries, "HSA-old (not in list)")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"

    def test_unlisted_401k_not_flagged(self):
        """401k isn't in the exact list — should NOT match (no regex fallback)."""
        entries, _, _ = loader.load_string(self._ledger(["Assets:Retirement:HSA:Cash"]))
        txn = _find_txn(entries, "401k (not in list)")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"

    def test_multiple_listed_accounts_all_flagged(self):
        ledger = (
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': [\n"
            "        'Assets:Retirement:HSA:Cash',\n"
            "        'Assets:Retirement:401k:Cash'\n"
            "    ],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Assets:Retirement:401k:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD

2026-01-15 * "HSA exact"
    Assets:Retirement:HSA:Cash               1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD

2026-01-16 * "401k exact"
    Assets:Retirement:401k:Cash               2000 USD
    Income:CapTech:Employer-Contribution     -2000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        for narration in ("HSA exact", "401k exact"):
            txn = _find_txn(entries, narration)
            assert "missing-contribution-year" in txn.tags
            assert txn.flag == "!"


class TestCombinedAccountsAndPatterns:
    """destination_accounts and destination_patterns together form a union."""

    LEDGER_TEMPLATE = (
        'option "operating_currency" "USD"\n'
        'plugin "beancount_plugins.missing_contribution_year" "{\n'
        "    'destination_accounts': ['Assets:Retirement:HSA-old:Cash'],\n"
        "    'destination_patterns': ['401k'],\n"
        "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
        '}"'
        + """

2026-01-01 open Assets:Retirement:HSA-old:Cash USD
2026-01-01 open Assets:Retirement:401k:Cash USD
2026-01-01 open Assets:Retirement:IRA:Vanguard USD
2026-01-01 open Income:CapTech:Employer-Contribution USD

2026-01-15 * "HSA-old via exact"
    Assets:Retirement:HSA-old:Cash           1000 USD
    Income:CapTech:Employer-Contribution    -1000 USD

2026-01-16 * "401k via pattern"
    Assets:Retirement:401k:Cash             2000 USD
    Income:CapTech:Employer-Contribution   -2000 USD

2026-01-17 * "IRA Vanguard (no match)"
    Assets:Retirement:IRA:Vanguard          500 USD
    Income:CapTech:Employer-Contribution    -500 USD
"""
    )

    def test_exact_match_works(self):
        entries, _, _ = loader.load_string(self.LEDGER_TEMPLATE)
        txn = _find_txn(entries, "HSA-old via exact")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_pattern_match_works(self):
        entries, _, _ = loader.load_string(self.LEDGER_TEMPLATE)
        txn = _find_txn(entries, "401k via pattern")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_account_matching_neither_skipped(self):
        """IRA:Vanguard isn't in exact list and doesn't match the '401k' pattern."""
        entries, _, _ = loader.load_string(self.LEDGER_TEMPLATE)
        txn = _find_txn(entries, "IRA Vanguard (no match)")
        assert "missing-contribution-year" not in txn.tags
        assert txn.flag == "*"


class TestAccountValidation:
    """Validation: explicitly-configured accounts must have Open directives."""

    def test_valid_accounts_no_error(self):
        """All configured accounts have Open directives → no validation errors."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA:Cash'],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD
"""
        )
        plugin_errors = [e for e in errors if "missing_contribution_year" in e.message]
        assert plugin_errors == []

    def test_unknown_destination_account_errors(self):
        """A destination_accounts entry with no Open directive → load fails."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA:Cash', 'Assets:Typos:Here'],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD
"""
        )
        assert any(
            "Assets:Typos:Here" in e.message and "destination_accounts" in e.message
            for e in errors
        )

    def test_unknown_counterparty_account_errors(self):
        """A counterparty_accounts entry with no Open directive → load fails."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA:Cash'],\n"
            "    'counterparty_accounts': ['Income:Nope:Wrong']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
"""
        )
        assert any(
            "Income:Nope:Wrong" in e.message and "counterparty_accounts" in e.message
            for e in errors
        )

    def test_parent_open_accepts_child_account(self):
        """`open Assets:Bank` implicitly opens Assets:Bank:Checking."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Bank:Checking'],\n"
            "    'counterparty_accounts': ['Income:X']\n"
            '}"'
            + """

2026-01-01 open Assets:Bank USD
2026-01-01 open Income:X USD
"""
        )
        plugin_errors = [e for e in errors if "missing_contribution_year" in e.message]
        assert plugin_errors == []

    def test_defaults_not_validated(self):
        """No config provided → defaults are used and NOT validated.

        The default counterparty list references accounts that don't exist
        in this test ledger, but no validation error should fire because
        defaults are trusted.
        """
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year"\n'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
"""
        )
        plugin_errors = [e for e in errors if "missing_contribution_year" in e.message]
        assert plugin_errors == []

    def test_empty_destination_accounts_skips_validation(self):
        """Explicit empty destination_accounts = [] → nothing to validate."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': [],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD
"""
        )
        dest_errors = [
            e
            for e in errors
            if "missing_contribution_year" in e.message
            and "destination_accounts" in e.message
        ]
        assert dest_errors == []

    def test_unparseable_config_skips_validation(self):
        """If config can't be parsed, defaults are used and not validated."""
        entries_list = [
            data.Open(
                meta={"filename": "<test>"},
                date=__import__("datetime").date(2026, 1, 1),
                account="Assets:Foo",
                currencies=[],
                booking=None,
            ),
        ]
        options = {"filename": "<test>"}
        _, errors = missing_contribution_year(
            entries_list, options, config="not-valid-config"
        )
        # No validation errors since config couldn't be parsed.
        assert not any("references unknown account" in e.message for e in errors)

    def test_multiple_invalid_accounts_all_reported(self):
        """Every invalid account is reported — not just the first."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': [\n"
            "        'Assets:Wrong1',\n"
            "        'Assets:Wrong2'\n"
            "    ],\n"
            "    'counterparty_accounts': ['Income:Wrong3']\n"
            '}"'
            + """
"""
        )
        assert any("Assets:Wrong1" in e.message for e in errors)
        assert any("Assets:Wrong2" in e.message for e in errors)
        assert any("Income:Wrong3" in e.message for e in errors)

    def test_typo_in_counterparty_caught(self):
        """Common real-world case: typo in counterparty account name."""
        entries, errors, _ = loader.load_string(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA:Cash'],\n"
            "    'counterparty_accounts': ['Income:Captech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD
"""
        )
        # Note: typo 'Captech' vs 'CapTech' — different capitalization.
        assert any("Income:Captech:Employer-Contribution" in e.message for e in errors)


class TestAccountValidationHelpers:
    """Unit tests for the Open-directive helpers."""

    def test_opened_accounts_collects_all_opens(self):
        from beancount_plugins.missing_contribution_year import (
            _opened_accounts,
        )

        entries = [
            data.Open(
                meta={"filename": "<test>"},
                date=__import__("datetime").date(2026, 1, 1),
                account="Assets:Bank",
                currencies=[],
                booking=None,
            ),
            data.Open(
                meta={"filename": "<test>"},
                date=__import__("datetime").date(2026, 1, 1),
                account="Income:Salary",
                currencies=[],
                booking=None,
            ),
            data.Transaction(
                meta={"filename": "<test>"},
                date=__import__("datetime").date(2026, 1, 15),
                flag="*",
                payee=None,
                narration="nope",
                tags=frozenset(),
                links=frozenset(),
                postings=[],
            ),
        ]
        opened = _opened_accounts(entries)
        assert "Assets:Bank" in opened
        assert "Income:Salary" in opened
        # Transactions are not Open directives.
        assert len(opened) == 2

    def test_is_account_valid_exact_match(self):
        from beancount_plugins.missing_contribution_year import _is_account_valid

        opened = frozenset({"Assets:Bank", "Income:Salary"})
        assert _is_account_valid("Assets:Bank", opened)
        assert not _is_account_valid("Assets:Other", opened)

    def test_is_account_valid_parent_match(self):
        from beancount_plugins.missing_contribution_year import _is_account_valid

        opened = frozenset({"Assets:Bank"})
        # Subaccount is implicitly open via parent.
        assert _is_account_valid("Assets:Bank:Checking", opened)
        assert _is_account_valid("Assets:Bank:Checking:Savings", opened)

    def test_is_account_valid_no_parent(self):
        from beancount_plugins.missing_contribution_year import _is_account_valid

        opened = frozenset({"Assets:Bank"})
        # Unrelated root account — no parent match.
        assert not _is_account_valid("Liabilities:CreditCard", opened)


class TestEdgeCases:
    def test_three_posting_destination_with_non_counterparty(self):
        """3-posting txn: HSA dest + 2 sources, neither source is a counterparty."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Mixed sources"
    Assets:Retirement:HSA:Cash    500 USD
    Assets:Banking:Checking      -300 USD
    Expenses:Groceries          -200 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Mixed sources")
        assert "missing-contribution-year" not in txn.tags

    def test_three_posting_destination_with_counterparty(self):
        """3-posting txn: HSA dest + checking (no) + employer contribution (yes)."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Mixed with employer"
    Assets:Retirement:HSA:Cash               500 USD
    Assets:Banking:Checking                -200 USD
    Income:CapTech:Employer-Contribution    -300 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Mixed with employer")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_invalid_config_returns_errors(self):
        entries = []
        options = {"filename": "<test>"}
        _, errors = missing_contribution_year(entries, options, config="not-valid")
        assert any("Invalid config" in e.message for e in errors)

    def test_invalid_config_still_processes_entries(self):
        """A bad config falls back to defaults, so valid entries are still tagged."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Still flagged despite bad config"
    Assets:Retirement:HSA:Cash       1000 USD
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Still flagged despite bad config")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"

    def test_empty_destination_accounts_falls_through_to_patterns(self):
        """Explicitly empty destination_accounts means 'use default patterns'."""
        ledger = (
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': [],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD

2026-01-15 * "Still uses pattern defaults"
    Assets:Retirement:HSA:Cash               1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Still uses pattern defaults")
        assert "missing-contribution-year" in txn.tags
        assert txn.flag == "!"


class TestPerformance:
    """Sanity checks for the exact-match optimization."""

    def test_exact_match_used_for_accounts_only(self):
        """A config with only destination_accounts (no patterns) should still work."""
        ledger = (
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA:Cash'],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD

2026-01-15 * "Exact match only"
    Assets:Retirement:HSA:Cash               1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        txn = _find_txn(entries, "Exact match only")
        assert "missing-contribution-year" in txn.tags

    def test_exact_match_does_not_run_regex_on_similar_accounts(self):
        """HSA-old shouldn't match because it isn't in the exact list."""
        ledger = (
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA-old:Cash'],\n"
            "    'counterparty_accounts': ['Income:CapTech:Employer-Contribution']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA-old:Cash USD
2026-01-01 open Assets:Retirement:HSA:Cash USD
2026-01-01 open Income:CapTech:Employer-Contribution USD

2026-01-15 * "HSA-old exact match"
    Assets:Retirement:HSA-old:Cash           1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD

2026-01-16 * "HSA (not in exact list, no patterns)"
    Assets:Retirement:HSA:Cash               500 USD
    Income:CapTech:Employer-Contribution     -500 USD
"""
        )
        entries, _, _ = loader.load_string(ledger)
        # HSA-old is in exact list — should be flagged.
        txn = _find_txn(entries, "HSA-old exact match")
        assert "missing-contribution-year" in txn.tags
        # HSA is NOT in exact list and there are no patterns — should not match.
        txn = _find_txn(entries, "HSA (not in exact list, no patterns)")
        assert "missing-contribution-year" not in txn.tags
