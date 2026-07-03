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

OPTIONAL CONFIG (Python dict literal, supports multi-line):

    ; No config — promote all metadata keys:
    plugin "beancount_plugins.promote_account_metadata"

    ; Promote only specific keys (string or list):
    plugin "beancount_plugins.promote_account_metadata" "{
        'whitelist': 'tax-treatment'
    }"

    plugin "beancount_plugins.promote_account_metadata" "{
        'whitelist': ['tax-treatment', 'cost-center']
    }"

    ; Promote all keys except specific ones:
    plugin "beancount_plugins.promote_account_metadata" "{
        'blacklist': ['tag-expected', 'link-expected']
    }"

    ; If both provided, whitelist wins:
    plugin "beancount_plugins.promote_account_metadata" "{
        'whitelist': ['tax-treatment'],
        'blacklist': ['tag-expected']
    }"

CONFIG KEYS:
- whitelist: string or list of key names — only these keys will be promoted
- blacklist: string or list of key names — these keys will be excluded from promotion
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

import ast
import logging
from typing import Any

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("promote_account_metadata",)

_SYSTEM_KEYS: frozenset[str] = frozenset({"filename", "lineno"})


def _to_key_set(value: str | list[str]) -> set[str]:
    """Normalize a string or list of strings to a set of keys."""
    if isinstance(value, str):
        return {value}
    return set(value)


def _parse_config(
    config: str | None,
) -> tuple[set[str] | None, set[str] | None, list[ParserError]]:
    """Parse Python-literal config string into whitelist and blacklist sets.

    Accepts Python dict syntax — single or double quotes, string or list values:
        {'whitelist': 'tax-treatment'}
        {'blacklist': ['tag-expected', 'link-expected']}

    Returns (whitelist, blacklist, errors). If whitelist is present, blacklist is
    always None (whitelist wins). On parse error returns (None, None, [error]).
    """
    if not config:
        return None, None, []

    try:
        config_data: dict[str, Any] = ast.literal_eval(config)
    except (ValueError, SyntaxError) as e:
        return (
            None,
            None,
            [
                ParserError(
                    source={"filename": "plugin config", "lineno": 0},
                    message=f"promote_account_metadata: Invalid config: {e}",
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
        whitelist = _to_key_set(config_data["whitelist"])
    elif "blacklist" in config_data:
        blacklist = _to_key_set(config_data["blacklist"])

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

    logger.debug(
        "promote_account_metadata: promoted %d metadata values", promoted_count
    )
    return new_entries, errors
