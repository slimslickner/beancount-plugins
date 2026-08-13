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


def _plugin_errors(ledger):
    """Return plugin error messages from loading the given ledger."""
    _, errors, _ = loader.load_string(ledger)
    return [e.message for e in errors if "missing 'contribution-year'" in e.message]


def _has_error_for(errors, narration):
    """True if any plugin error mentions this narration."""
    return any(narration in e for e in errors)


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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "HSA contribution")

    def test_contribution_year_on_posting_skipped(self):
        """contribution-year on the destination posting → no error."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "HSA with year on posting"
    Assets:Retirement:HSA:Cash       1000 USD
        contribution-year: "2026"
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        errors = _plugin_errors(ledger)
        assert not _has_error_for(errors, "HSA with year on posting")

    def test_contribution_year_on_transaction_errors(self):
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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "HSA with year on txn")

    def test_contribution_year_on_counterparty_posting_errors(self):
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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "Year on the wrong posting")

    def test_non_matching_counterparty_skipped(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "HSA from random"
    Assets:Retirement:HSA:Cash   500 USD
    Assets:Banking:Checking     -500 USD
"""
        )
        errors = _plugin_errors(ledger)
        assert not _has_error_for(errors, "HSA from random")

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
        errors = _plugin_errors(ledger)
        assert not _has_error_for(errors, "Custom plan contribution")

    def test_employer_contribution_errors(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "401k employer match"
    Assets:Retirement:HSA:Cash               1000 USD
    Income:CapTech:Employer-Contribution     -1000 USD
"""
        )
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "401k employer match")

    def test_no_destination_no_error(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Groceries"
    Expenses:Groceries   100 USD
    Assets:Banking:Checking -100 USD
"""
        )
        errors = _plugin_errors(ledger)
        assert not _has_error_for(errors, "Groceries")

    def test_clean_ledger_no_errors(self):
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Clean HSA"
    Assets:Retirement:HSA:Cash       1000 USD
        contribution-year: "2026"
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        errors = _plugin_errors(ledger)
        assert errors == []


class TestExactMatchOnly:
    """When destination_accounts is the only config, only listed accounts match."""

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

    def test_listed_account_errors(self):
        errors = _plugin_errors(self._ledger(["Assets:Retirement:HSA:Cash"]))
        assert _has_error_for(errors, "Exact match contribution")

    def test_unlisted_hsa_old_no_error(self):
        """HSA-old isn't in the exact list — should NOT match."""
        errors = _plugin_errors(self._ledger(["Assets:Retirement:HSA:Cash"]))
        assert not _has_error_for(errors, "HSA-old (not in list)")

    def test_unlisted_401k_no_error(self):
        """401k isn't in the exact list — should NOT match (no regex fallback)."""
        errors = _plugin_errors(self._ledger(["Assets:Retirement:HSA:Cash"]))
        assert not _has_error_for(errors, "401k (not in list)")

    def test_multiple_listed_accounts_all_error(self):
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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "HSA exact")
        assert _has_error_for(errors, "401k exact")


class TestCombinedAccountsAndPatterns:
    """destination_accounts and destination_patterns together form a union."""

    LEDGER = (
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

    def test_exact_match_errors(self):
        errors = _plugin_errors(self.LEDGER)
        assert _has_error_for(errors, "HSA-old via exact")

    def test_pattern_match_errors(self):
        errors = _plugin_errors(self.LEDGER)
        assert _has_error_for(errors, "401k via pattern")

    def test_account_matching_neither_no_error(self):
        """IRA:Vanguard isn't in exact list and doesn't match the '401k' pattern."""
        errors = _plugin_errors(self.LEDGER)
        assert not _has_error_for(errors, "IRA Vanguard (no match)")


class TestAccountValidation:
    """Validation: explicitly-configured accounts must have Open directives."""

    def _plugin_validation_errors(self, ledger):
        """Return validation errors (not transaction violations)."""
        _, errors, _ = loader.load_string(ledger)
        return [e.message for e in errors if "unknown account" in e.message]

    def test_valid_accounts_no_error(self):
        """All configured accounts have Open directives → no validation errors."""
        errors = self._plugin_validation_errors(
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
        assert errors == []

    def test_unknown_destination_account_errors(self):
        """A destination_accounts entry with no Open directive → load fails."""
        errors = self._plugin_validation_errors(
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
        assert any("Assets:Typos:Here" in e for e in errors)

    def test_unknown_counterparty_account_errors(self):
        """A counterparty_accounts entry with no Open directive → load fails."""
        errors = self._plugin_validation_errors(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year" "{\n'
            "    'destination_accounts': ['Assets:Retirement:HSA:Cash'],\n"
            "    'counterparty_accounts': ['Income:Nope:Wrong']\n"
            '}"'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
"""
        )
        assert any("Income:Nope:Wrong" in e for e in errors)

    def test_parent_open_accepts_child_account(self):
        """`open Assets:Bank` implicitly opens Assets:Bank:Checking."""
        errors = self._plugin_validation_errors(
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
        assert errors == []

    def test_defaults_not_validated(self):
        """No config provided → defaults are used and NOT validated."""
        errors = self._plugin_validation_errors(
            'option "operating_currency" "USD"\n'
            'plugin "beancount_plugins.missing_contribution_year"\n'
            + """

2026-01-01 open Assets:Retirement:HSA:Cash USD
"""
        )
        assert errors == []

    def test_empty_destination_accounts_skips_validation(self):
        """Explicit empty destination_accounts = [] → nothing to validate."""
        errors = self._plugin_validation_errors(
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
        assert errors == []

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
        assert not any("unknown account" in e.message for e in errors)

    def test_multiple_invalid_accounts_all_reported(self):
        """Every invalid account is reported — not just the first."""
        errors = self._plugin_validation_errors(
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
        assert any("Assets:Wrong1" in e for e in errors)
        assert any("Assets:Wrong2" in e for e in errors)
        assert any("Income:Wrong3" in e for e in errors)

    def test_typo_in_counterparty_caught(self):
        """Common real-world case: typo in counterparty account name."""
        errors = self._plugin_validation_errors(
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
        assert any("Income:Captech:Employer-Contribution" in e for e in errors)


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
        errors = _plugin_errors(ledger)
        assert not _has_error_for(errors, "Mixed sources")

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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "Mixed with employer")

    def test_invalid_config_returns_errors(self):
        entries = []
        options = {"filename": "<test>"}
        _, errors = missing_contribution_year(entries, options, config="not-valid")
        assert any("Invalid config" in e.message for e in errors)

    def test_invalid_config_still_validates_transactions(self):
        """A bad config falls back to defaults, so transaction violations still emit errors."""
        ledger = (
            _BASE_LEDGER
            + """
2026-01-15 * "Still errored despite bad config"
    Assets:Retirement:HSA:Cash       1000 USD
    Equity:ZeroSumMatched:Transfers -1000 USD
"""
        )
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "Still errored despite bad config")

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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "Still uses pattern defaults")


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
        errors = _plugin_errors(ledger)
        assert _has_error_for(errors, "Exact match only")

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
        errors = _plugin_errors(ledger)
        # HSA-old is in exact list — should error.
        assert _has_error_for(errors, "HSA-old exact match")
        # HSA is NOT in exact list and there are no patterns — should not error.
        assert not _has_error_for(errors, "HSA (not in exact list, no patterns)")
