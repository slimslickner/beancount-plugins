# promote_account_metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a beancount plugin that reads metadata from `Open` directives and promotes those key-value pairs onto any posting that uses that account.

**Architecture:** Two-phase pattern: (1) index Open directive metadata into `dict[account, dict[key, value]]` applying whitelist/blacklist config filter; (2) walk transactions and merge indexed metadata onto each posting — existing posting values win on conflict with a logged warning.

**Tech Stack:** Python 3.13+, beancount v3, pytest, json (stdlib)

## Global Constraints

- Python 3.13+ required (see `.python-version`)
- All changes must pass `uv run ruff check --fix`, `uv run ruff format`, `uv run ty check` with zero errors before committing
- Plugin function signature: `(entries: data.Entries, options_map: dict, config: str | None) -> tuple[data.Entries, list[ParserError]]`
- Config is an inline JSON string in the plugin declaration — not a file path
- System keys `filename` and `lineno` are never promoted (beancount internals)
- Tests use pytest; unit tests use `loader.load_string()`; integration tests extend `tests/sample.beancount`

---

### Task 1: Plugin implementation + unit tests

**Files:**
- Create: `beancount_plugins/promote_account_metadata.py`
- Create: `tests/test_promote_account_metadata.py`

**Interfaces:**
- Produces: `promote_account_metadata(entries: data.Entries, options_map: dict, config: str | None = None) -> tuple[data.Entries, list[ParserError]]`
- Produces: `_parse_config(config: str | None) -> tuple[set[str] | None, set[str] | None, list[ParserError]]` — returns `(whitelist, blacklist, errors)`; if whitelist is present, blacklist is `None`; invalid JSON or unknown keys return `(None, None, [error])`
- Produces: `_filter_keys(meta: dict[str, Any], whitelist: set[str] | None, blacklist: set[str] | None) -> dict[str, Any]` — whitelist beats blacklist; neither means return all keys

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_promote_account_metadata.py`:

```python
"""Unit tests for promote_account_metadata plugin."""

import logging

import pytest
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


def test_parse_config_whitelist():
    whitelist, blacklist, errors = _parse_config('{"whitelist": ["tax-treatment"]}')
    assert whitelist == {"tax-treatment"}
    assert blacklist is None
    assert errors == []


def test_parse_config_blacklist():
    whitelist, blacklist, errors = _parse_config('{"blacklist": ["tag-expected"]}')
    assert whitelist is None
    assert blacklist == {"tag-expected"}
    assert errors == []


def test_parse_config_both_whitelist_wins():
    whitelist, blacklist, errors = _parse_config(
        '{"whitelist": ["a"], "blacklist": ["b"]}'
    )
    assert whitelist == {"a"}
    assert blacklist is None
    assert errors == []


def test_parse_config_invalid_json():
    whitelist, blacklist, errors = _parse_config("not-json")
    assert whitelist is None
    assert blacklist is None
    assert len(errors) == 1
    assert "Invalid JSON" in errors[0].message


def test_parse_config_unknown_keys():
    whitelist, blacklist, errors = _parse_config('{"unknown_key": []}')
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
        e for e in entries
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
        config = ' "{\\"whitelist\\": [\\"tax-treatment\\"]}"'
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=config))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert "cost-center" not in posting.meta
        assert "internal-note" not in posting.meta

    def test_blacklist_excludes_listed_keys(self):
        config = ' "{\\"blacklist\\": [\\"internal-note\\"]}"'
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=config))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert posting.meta.get("cost-center") == "engineering"
        assert "internal-note" not in posting.meta

    def test_whitelist_wins_when_both_provided(self):
        config = (
            ' "{\\"whitelist\\": [\\"tax-treatment\\"],'
            ' \\"blacklist\\": [\\"tax-treatment\\"]}"'
        )
        entries, _, _ = loader.load_string(_MULTI_KEY_LEDGER.format(config=config))
        txn = _find_txn(entries, "Work expense")
        posting = _find_posting(txn, "Expenses:Work")
        assert posting.meta.get("tax-treatment") == "pre-tax"
        assert "cost-center" not in posting.meta
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/timtickner/dev/beancount-plugins && uv run pytest tests/test_promote_account_metadata.py -v 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError` — module does not exist yet

- [ ] **Step 3: Implement the plugin**

Create `beancount_plugins/promote_account_metadata.py`:

```python
#!/usr/bin/env python3
"""Beancount plugin to promote Open directive metadata to transaction postings.

For each posting in a transaction, this plugin looks up the account's Open directive
and copies any metadata key-value pairs onto the posting. This allows account-level
annotations (e.g. tax-treatment, department, cost-center) to flow down to individual
postings for use in queries and downstream plugins.

WHAT IT DOES:
- Indexes all Open directives and their metadata at load time
- For each transaction posting, merges matching account metadata onto the posting
- Existing posting values take precedence over account metadata (posting wins on conflict)
- Logs a WARNING (visible with bean-check -v) when a conflict is detected
- System keys (filename, lineno) from Open directives are never promoted

USAGE:
Load before any metadata validation plugins (e.g. check_valid_metadata):

    plugin "beancount_plugins.promote_account_metadata"

OPTIONAL CONFIG (inline JSON string in the plugin declaration):

    ; Promote only specific keys:
    plugin "beancount_plugins.promote_account_metadata" "{\"whitelist\": [\"tax-treatment\"]}"

    ; Promote all keys except specific ones:
    plugin "beancount_plugins.promote_account_metadata" "{\"blacklist\": [\"tag-expected\", \"link-expected\"]}"

    ; If both whitelist and blacklist are provided, whitelist wins:
    plugin "beancount_plugins.promote_account_metadata" "{\"whitelist\": [\"a\"], \"blacklist\": [\"b\"]}"

CONFIG KEYS:
- whitelist: list of key names — only these keys will be promoted
- blacklist: list of key names — these keys will be excluded from promotion
- If both provided, whitelist wins and blacklist is ignored
- If neither provided, all metadata keys (except system keys) are promoted

EXAMPLE:

    2026-06-01 open Expenses:Taxes:Federal USD
      tax-treatment: "pre-tax"

    2026-06-02 * "Paycheck"
      Income:Employer:Paycheck -1000 USD
      Assets:Checking           800 USD
      Expenses:Taxes:Federal    200 USD

    After processing, the Federal posting gains:

      Expenses:Taxes:Federal  200 USD
        tax-treatment: "pre-tax"

CONFLICT RESOLUTION:
If a posting already has a key that would be promoted from its account's Open directive,
the existing posting value is preserved and a warning is emitted:

    WARNING promote_account_metadata: conflict on account 'X' key 'Y'
            in transaction 'Z' — posting value wins

PLUGIN LOAD ORDER:
Load before check_valid_metadata so promoted keys are present when validation runs.
If using check_valid_metadata, add promoted keys to the posting section of your
metadata_schema.yaml, otherwise they will be flagged as unknown.
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import json
import logging
from typing import Any

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("promote_account_metadata",)

_SYSTEM_KEYS: frozenset[str] = frozenset({"filename", "lineno"})


def _parse_config(
    config: str | None,
) -> tuple[set[str] | None, set[str] | None, list[ParserError]]:
    """Parse inline JSON config string into whitelist and blacklist sets.

    Returns (whitelist, blacklist, errors). If whitelist is present, blacklist is
    always None (whitelist wins). On parse error returns (None, None, [error]).
    """
    if not config:
        return None, None, []

    try:
        config_data: dict[str, Any] = json.loads(config)
    except json.JSONDecodeError as e:
        return (
            None,
            None,
            [
                ParserError(
                    source={"filename": "plugin config", "lineno": 0},
                    message=f"promote_account_metadata: Invalid JSON config: {e}",
                    entry=None,
                )
            ],
        )

    unknown = set(config_data.keys()) - {"whitelist", "blacklist"}
    if unknown:
        return (
            None,
            None,
            [
                ParserError(
                    source={"filename": "plugin config", "lineno": 0},
                    message=(
                        f"promote_account_metadata: Unknown config keys: "
                        f"{', '.join(sorted(unknown))}. Allowed: whitelist, blacklist"
                    ),
                    entry=None,
                )
            ],
        )

    whitelist: set[str] | None = None
    blacklist: set[str] | None = None

    if "whitelist" in config_data:
        whitelist = set(config_data["whitelist"])
    elif "blacklist" in config_data:
        blacklist = set(config_data["blacklist"])

    return whitelist, blacklist, []


def _filter_keys(
    meta: dict[str, Any],
    whitelist: set[str] | None,
    blacklist: set[str] | None,
) -> dict[str, Any]:
    """Filter metadata keys by whitelist or blacklist. Whitelist beats blacklist."""
    if whitelist is not None:
        return {k: v for k, v in meta.items() if k in whitelist}
    if blacklist is not None:
        return {k: v for k, v in meta.items() if k not in blacklist}
    return dict(meta)


def promote_account_metadata(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> tuple[data.Entries, list[ParserError]]:
    """Promote Open directive metadata onto matching transaction postings.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional inline JSON string with 'whitelist' and/or 'blacklist' keys

    Returns:
        Tuple of (modified_entries, errors)
    """
    errors: list[ParserError] = []

    whitelist, blacklist, config_errors = _parse_config(config)
    if config_errors:
        errors.extend(config_errors)
        return entries, errors

    # Phase 1: index Open directive metadata, applying filter
    account_meta: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, data.Open):
            raw = {k: v for k, v in entry.meta.items() if k not in _SYSTEM_KEYS}
            filtered = _filter_keys(raw, whitelist, blacklist)
            if filtered:
                account_meta[entry.account] = filtered

    if not account_meta:
        logger.debug("promote_account_metadata: no account metadata to promote")
        return entries, errors

    # Phase 2: promote metadata onto postings
    new_entries: list[data.Directive] = []
    promoted_count = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            new_entries.append(entry)
            continue

        new_postings: list[data.Posting] = []
        for posting in entry.postings:
            promotable = account_meta.get(posting.account)
            if not promotable:
                new_postings.append(posting)
                continue

            new_meta = dict(posting.meta) if posting.meta else {}
            for key, value in promotable.items():
                if key in new_meta:
                    logger.warning(
                        "promote_account_metadata: conflict on account '%s' key '%s' "
                        "in transaction '%s' — posting value wins",
                        posting.account,
                        key,
                        entry.narration,
                    )
                else:
                    new_meta[key] = value
                    promoted_count += 1

            new_postings.append(posting._replace(meta=new_meta))

        new_entries.append(entry._replace(postings=new_postings))

    logger.debug("promote_account_metadata: promoted %d metadata values", promoted_count)
    return new_entries, errors
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/timtickner/dev/beancount-plugins && uv run pytest tests/test_promote_account_metadata.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Run code quality checks**

```bash
cd /Users/timtickner/dev/beancount-plugins && uv run ruff check --fix && uv run ruff format && uv run ty check
```

Expected: Zero errors on all three commands

- [ ] **Step 6: Commit**

```bash
git add beancount_plugins/promote_account_metadata.py tests/test_promote_account_metadata.py
git commit -m "feat: add promote_account_metadata plugin"
```

---

### Task 2: Integration with sample ledger

**Files:**
- Modify: `tests/metadata_schema.yaml` — add `tax-treatment` to `open` and `posting` sections
- Modify: `tests/sample.beancount` — add plugin declaration + new accounts + test transactions
- Modify: `tests/test_plugins.py` — add `TestPromoteAccountMetadata` class

The sample ledger loads `check_valid_metadata`, so any metadata on Open directives or
postings must be registered in the schema. We add `tax-treatment` to both `open` and
`posting` schema sections. We use a whitelist config `{"whitelist": ["tax-treatment"]}`
in the plugin declaration to avoid accidentally promoting plugin-control keys like
`tag-expected`, `link-expected`, and `tax-account-type` onto postings (which would then
fail schema validation as unknown posting keys).

**Interfaces:**
- Consumes: `promote_account_metadata` from Task 1

- [ ] **Step 1: Add `tax-treatment` to metadata_schema.yaml**

In `tests/metadata_schema.yaml`, add to the `open:` section (after the `tag-expected` block):

```yaml
    tax-treatment:
      label: "Tax treatment applied to this account's transactions"
      type: string
      required: false
```

And add to the `posting:` section (after the `tags` block):

```yaml
    tax-treatment:
      label: "Tax treatment promoted from account Open directive"
      type: string
      required: false
```

- [ ] **Step 2: Add plugin declaration to sample.beancount**

Add as the **first** plugin line (before `posting_tags`) in the plugin loading section:

```
plugin "beancount_plugins.promote_account_metadata" "{\"whitelist\": [\"tax-treatment\"]}"
```

- [ ] **Step 3: Add new Open accounts to sample.beancount**

In the account setup section (after `Equity:ZeroSum:Transfers`), add:

```
2026-01-01 open Expenses:TaxWithheld USD
  tax-treatment: "pre-tax"
2026-01-01 open Expenses:NoMeta USD
```

- [ ] **Step 4: Add test transactions to sample.beancount**

At the end of the file, add a new section:

```
; === Section 14: promote_account_metadata ===

; NO ERROR: tax-treatment promoted from Open directive to posting
2026-12-01 * "Tax withholding"
  Expenses:TaxWithheld  100.00 USD
  Assets:Checking      -100.00 USD

; NO ERROR: account without Open metadata — nothing promoted
2026-12-02 * "General no-meta expense"
  Expenses:NoMeta   50.00 USD
  Assets:Checking  -50.00 USD
```

- [ ] **Step 5: Add integration test class to test_plugins.py**

Add after `TestCheckValidMetadata` (before the `TestTransactionAccountPattern` section):

```python
# ---------------------------------------------------------------------------
# promote_account_metadata plugin
# ---------------------------------------------------------------------------


class TestPromoteAccountMetadata:
    def test_metadata_promoted_to_matching_posting(self, transactions):
        """tax-treatment from Open directive should appear on the matching posting."""
        txn = _find_txn(transactions, "Tax withholding")
        posting = _find_posting(txn, "Expenses:TaxWithheld")
        assert posting.meta.get("tax-treatment") == "pre-tax"

    def test_metadata_not_on_other_posting_in_same_txn(self, transactions):
        """Checking posting in the same txn should not receive tax-treatment."""
        txn = _find_txn(transactions, "Tax withholding")
        posting = _find_posting(txn, "Assets:Checking")
        assert "tax-treatment" not in posting.meta

    def test_account_without_open_metadata_unaffected(self, transactions):
        """Posting to an account with no Open metadata should be unchanged."""
        txn = _find_txn(transactions, "General no-meta expense")
        posting = _find_posting(txn, "Expenses:NoMeta")
        assert "tax-treatment" not in posting.meta
```

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/timtickner/dev/beancount-plugins && uv run pytest tests/ -v
```

Expected: All tests PASS with no new failures

- [ ] **Step 7: Run code quality checks**

```bash
cd /Users/timtickner/dev/beancount-plugins && uv run ruff check --fix && uv run ruff format && uv run ty check
```

Expected: Zero errors

- [ ] **Step 8: Commit**

```bash
git add tests/sample.beancount tests/metadata_schema.yaml tests/test_plugins.py
git commit -m "test: integrate promote_account_metadata into sample ledger"
```
