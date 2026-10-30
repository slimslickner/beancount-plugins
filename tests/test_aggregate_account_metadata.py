"""Unit tests for aggregate_account_metadata plugin."""

import logging

from beancount import loader
from beancount.core import data

from beancount_plugins.aggregate_account_metadata import _parse_config


def _load(config: str | None, body: str):
    ledger = 'option "operating_currency" "USD"\n'
    if config is not None:
        ledger += (
            f'plugin "beancount_plugins.aggregate_account_metadata" "{config}"\n'
        )
    ledger += body
    return loader.load_string(ledger)


def _find_open(entries, account):
    return next(
        e for e in entries if isinstance(e, data.Open) and e.account == account
    )


def _plugin_errors(errors):
    return [e for e in errors if "aggregate_account_metadata" in e.message]


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_parse_config_none():
    specs, errors = _parse_config(None)
    assert specs == []
    assert errors == []


def test_parse_config_empty_string():
    specs, errors = _parse_config("")
    assert specs == []
    assert errors == []


def test_parse_config_valid_single():
    specs, errors = _parse_config(
        "{'aggregations': {'asset-class': {'source': 'account-type', "
        "'maps': {'taxable': ['checking', 'savings']}}}}"
    )
    assert errors == []
    assert len(specs) == 1
    spec = specs[0]
    assert spec.key == "asset-class"
    assert spec.source == "account-type"
    assert spec.mode == "strict"
    assert spec.default is None
    assert spec.value_map == {"checking": "taxable", "savings": "taxable"}


def test_parse_config_valid_multiple():
    specs, errors = _parse_config(
        "{'aggregations': {"
        "'asset-class': {'source': 'account-type', 'maps': {'taxable': ['checking']}}, "
        "'liquidity': {'source': 'account-type', 'maps': {'liquid': ['checking']}}"
        "}}"
    )
    assert errors == []
    assert {s.key for s in specs} == {"asset-class", "liquidity"}


def test_parse_config_multiline():
    config = (
        "{\n"
        "    'aggregations': {\n"
        "        'asset-class': {\n"
        "            'source': 'account-type',\n"
        "            'maps': {'taxable': ['checking']}\n"
        "        }\n"
        "    }\n"
        "}"
    )
    specs, errors = _parse_config(config)
    assert errors == []
    assert len(specs) == 1


def test_parse_config_string_map_value():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'maps': {'a': 'checking'}}}}"
    )
    assert errors == []
    assert specs[0].value_map == {"checking": "a"}


def test_parse_config_default_mode():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'mode': 'default', "
        "'default': 'other', 'maps': {'a': ['p']}}}}"
    )
    assert errors == []
    assert specs[0].mode == "default"
    assert specs[0].default == "other"


def test_parse_config_bool_map_value():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', "
        "'maps': {True: ['checking'], False: ['401k']}}}}"
    )
    assert errors == []
    assert specs[0].value_map == {"checking": True, "401k": False}


def test_parse_config_bool_default():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'mode': 'default', "
        "'default': True, 'maps': {'a': ['p']}}}}"
    )
    assert errors == []
    assert specs[0].default is True


def test_parse_config_false_default_allowed():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'mode': 'default', "
        "'default': False, 'maps': {'a': ['p']}}}}"
    )
    assert errors == []
    assert specs[0].default is False


def test_parse_config_int_map_value_rejected():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'maps': {1: ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "non-string/bool or empty" in errors[0].message


def test_parse_config_none_map_value_rejected():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'maps': {None: ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "non-string/bool or empty" in errors[0].message


def test_parse_config_int_default_rejected():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'mode': 'default', "
        "'default': 3, 'maps': {'a': ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "requires a non-empty 'default'" in errors[0].message


def test_parse_config_invalid_syntax():
    specs, errors = _parse_config("not valid python")
    assert specs == []
    assert len(errors) == 1
    assert "Invalid config" in errors[0].message


def test_parse_config_not_a_dict():
    specs, errors = _parse_config("['aggregations']")
    assert specs == []
    assert len(errors) == 1
    assert "must be a dict" in errors[0].message


def test_parse_config_unknown_top_keys():
    specs, errors = _parse_config("{'aggregations': {'x': {}}, 'bogus': []}")
    assert specs == []
    assert len(errors) == 1
    assert "bogus" in errors[0].message


def test_parse_config_missing_aggregations():
    specs, errors = _parse_config("{}")
    assert specs == []
    assert len(errors) == 1
    assert "aggregations" in errors[0].message


def test_parse_config_empty_aggregations():
    specs, errors = _parse_config("{'aggregations': {}}")
    assert specs == []
    assert len(errors) == 1
    assert "non-empty dict" in errors[0].message


def test_parse_config_aggregation_not_dict():
    specs, errors = _parse_config("{'aggregations': {'x': ['nope']}}")
    assert specs == []
    assert len(errors) == 1
    assert "must be a dict" in errors[0].message


def test_parse_config_unknown_agg_keys():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'maps': {'a': ['p']}, 'bogus': 1}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "bogus" in errors[0].message


def test_parse_config_missing_source():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'maps': {'a': ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "source" in errors[0].message


def test_parse_config_empty_maps():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'maps': {}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "maps" in errors[0].message


def test_parse_config_map_value_wrong_type():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'maps': {'a': [1, 2]}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "list of strings" in errors[0].message


def test_parse_config_invalid_mode():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'mode': 'lenient', "
        "'maps': {'a': ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "invalid mode" in errors[0].message


def test_parse_config_default_mode_without_default():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'mode': 'default', "
        "'maps': {'a': ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "requires a non-empty 'default'" in errors[0].message


def test_parse_config_default_with_strict_mode():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', 'default': 'other', "
        "'maps': {'a': ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "'default' is only valid" in errors[0].message


def test_parse_config_overlap():
    specs, errors = _parse_config(
        "{'aggregations': {'x': {'source': 't', "
        "'maps': {'a': ['p'], 'b': ['p']}}}}"
    )
    assert specs == []
    assert len(errors) == 1
    assert "multiple outputs" in errors[0].message


# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------

_BASIC_BODY = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Assets:Retirement USD
  account-type: "401k"
"""

_BASIC_CONFIG = (
    "{'aggregations': {'asset-class': {'source': 'account-type', "
    "'maps': {'taxable': ['checking'], 'retirement': ['401k']}}}}"
)


class TestBasic:
    def test_derived_key_written_to_open(self):
        entries, _, _ = _load(_BASIC_CONFIG, _BASIC_BODY)
        assert _find_open(entries, "Assets:Checking").meta["asset-class"] == "taxable"
        assert (
            _find_open(entries, "Assets:Retirement").meta["asset-class"]
            == "retirement"
        )

    def test_source_key_preserved(self):
        entries, _, _ = _load(_BASIC_CONFIG, _BASIC_BODY)
        assert _find_open(entries, "Assets:Checking").meta["account-type"] == "checking"

    def test_no_plugin_errors_on_valid_ledger(self):
        _, errors, _ = _load(_BASIC_CONFIG, _BASIC_BODY)
        assert _plugin_errors(errors) == []

    def test_multiple_aggregations(self):
        config = (
            "{'aggregations': {"
            "'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking'], 'retirement': ['401k']}}, "
            "'liquidity': {'source': 'account-type', "
            "'maps': {'liquid': ['checking'], 'illiquid': ['401k']}}"
            "}}"
        )
        entries, _, _ = _load(config, _BASIC_BODY)
        checking = _find_open(entries, "Assets:Checking").meta
        assert checking["asset-class"] == "taxable"
        assert checking["liquidity"] == "liquid"

    def test_derived_key_not_on_postings(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Expenses:Stuff USD

2026-01-02 * "Buy"
  Expenses:Stuff   10 USD
  Assets:Checking -10 USD
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        entries, _, _ = _load(config, body)
        txn = next(e for e in entries if isinstance(e, data.Transaction))
        posting = next(
            p for p in txn.postings if p.account == "Assets:Checking"
        )
        assert "asset-class" not in (posting.meta or {})
        assert _find_open(entries, "Assets:Checking").meta["asset-class"] == "taxable"

    def test_open_without_source_key_untouched(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Assets:Other USD
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        entries, _, _ = _load(config, body)
        assert "asset-class" not in (_find_open(entries, "Assets:Other").meta or {})


class TestBoolOutput:
    def test_bool_derived_values_written(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Assets:Retirement USD
  account-type: "401k"
"""
        config = (
            "{'aggregations': {'taxable': {'source': 'account-type', "
            "'maps': {True: ['checking'], False: ['401k']}}}}"
        )
        entries, errors, _ = _load(config, body)
        assert _plugin_errors(errors) == []
        assert _find_open(entries, "Assets:Checking").meta["taxable"] is True
        assert _find_open(entries, "Assets:Retirement").meta["taxable"] is False

    def test_false_default_written(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Assets:Cash USD
  account-type: "savings"
"""
        config = (
            "{'aggregations': {'taxable': {'source': 'account-type', "
            "'mode': 'default', 'default': False, "
            "'maps': {True: ['checking']}}}}"
        )
        entries, errors, _ = _load(config, body)
        assert _plugin_errors(errors) == []
        assert _find_open(entries, "Assets:Checking").meta["taxable"] is True
        assert _find_open(entries, "Assets:Cash").meta["taxable"] is False


class TestDefaultMode:
    def test_unmapped_value_falls_back(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Assets:Cash USD
  account-type: "savings"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'mode': 'default', 'default': 'other', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        entries, errors, _ = _load(config, body)
        assert _plugin_errors(errors) == []
        assert _find_open(entries, "Assets:Checking").meta["asset-class"] == "taxable"
        assert _find_open(entries, "Assets:Cash").meta["asset-class"] == "other"

    def test_default_mode_no_uncovered_error(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
2026-01-01 open Assets:Weird USD
  account-type: "something-else"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'mode': 'default', 'default': 'other', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        _, errors, _ = _load(config, body)
        assert _plugin_errors(errors) == []


class TestStrictMode:
    def test_unmapped_value_errors(self):
        body = """
2026-01-01 open Assets:Weird USD
  account-type: "unmapped-value"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        _, errors, _ = _load(config, body)
        messages = [e.message for e in _plugin_errors(errors)]
        assert any("not mapped" in m for m in messages)

    def test_unmapped_error_points_at_open_line(self):
        body = """
2026-01-01 open Assets:Weird USD
  account-type: "unmapped-value"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        _, errors, _ = _load(config, body)
        unmatched = next(
            e for e in _plugin_errors(errors) if "not mapped" in e.message
        )
        assert unmatched.source["lineno"] == 4


class TestCoverage:
    def test_declared_but_unused_errors(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking'], 'retirement': ['401k']}}}}"
        )
        _, errors, _ = _load(config, body)
        messages = [e.message for e in _plugin_errors(errors)]
        assert any("never observed" in m and "401k" in m for m in messages)

    def test_declared_but_unused_errors_in_default_mode(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'mode': 'default', 'default': 'other', "
            "'maps': {'taxable': ['checking'], 'retirement': ['401k']}}}}"
        )
        _, errors, _ = _load(config, body)
        messages = [e.message for e in _plugin_errors(errors)]
        assert any("never observed" in m and "401k" in m for m in messages)


class TestConflict:
    def test_existing_value_wins(self):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
  asset-class: "manual"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        entries, _, _ = _load(config, body)
        assert _find_open(entries, "Assets:Checking").meta["asset-class"] == "manual"

    def test_conflict_logs_warning(self, caplog):
        body = """
2026-01-01 open Assets:Checking USD
  account-type: "checking"
  asset-class: "manual"
"""
        config = (
            "{'aggregations': {'asset-class': {'source': 'account-type', "
            "'maps': {'taxable': ['checking']}}}}"
        )
        with caplog.at_level(
            logging.WARNING,
            logger="beancount_plugins.aggregate_account_metadata",
        ):
            _load(config, body)
        assert any("conflict" in r.message.lower() for r in caplog.records)
