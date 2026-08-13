#!/usr/bin/env python3
"""Beancount plugin to error on contributions missing a contribution-year metadata.

Retirement contributions should carry a `contribution-year` metadata key on
the receiving posting so downstream queries can group contributions by tax
year. This plugin errors on any contribution that arrives without that key,
so bean-check (and any other loader) refuses to load the ledger until fixed.

WHAT IT DOES:
- Identifies transactions that match ALL of these criteria:
  - At least one posting is a "destination" — its account is in the configured
    destination accounts list (exact match) OR matches one of the configured
    destination regex patterns.
  - At least one OTHER posting is a "counterparty" — its account exactly
    matches one of the configured counterparty accounts (the known
    contribution sources: payroll, employer match, transfers from checking).
  - The qualifying destination posting does NOT carry `contribution-year` as
    posting-level metadata. (The year lives on the *receiving posting*, not on
    the transaction itself, so per-destination contributions can be queried.)
- Emits a ParserError for each violation with the transaction's file/line.

EXACT-MATCH VS REGEX:
destination_accounts is the PRIMARY way to specify destinations — explicit,
O(1), no regex foot-guns. When provided (non-empty), the default
destination_patterns are NOT used; the destination set becomes exactly what
you listed. To combine exact accounts with regex patterns, set both keys
explicitly. An empty destination_accounts list (`[]`) leaves pattern defaults
in place.

USAGE:
In your main ledger file:

    plugin "beancount_plugins.missing_contribution_year"

OPTIONAL CONFIG (Python dict literal via ast.literal_eval — same style as
promote_account_metadata; single or double quotes, single string or list):

    ; Use defaults (HSA / 401k / IRA / DC as regex patterns, the known
    ; contribution sources for this ledger as counterparties):
    plugin "beancount_plugins.missing_contribution_year"

    ; Exact-match destinations (PREFERRED — no regex foot-guns, O(1) lookups):
    plugin "beancount_plugins.missing_contribution_year" "{
        'destination_accounts': [
            'Assets:Retirement:HSA:Fidelity-HSA:Cash',
            'Assets:Retirement:401k:Fidelity-401k:Cash',
            'Assets:Retirement:IRA:Vanguard:Cash'
        ]
    }"

    ; Combine exact accounts with regex patterns (union — either qualifies):
    plugin "beancount_plugins.missing_contribution_year" "{
        'destination_accounts': [
            'Assets:Retirement:HSA-old:Fidelity:Cash'
        ],
        'destination_patterns': ['HSA', '401k', 'IRA']
    }"

    ; Override the counterparty list (defaults for destinations still apply):
    plugin "beancount_plugins.missing_contribution_year" "{
        'counterparty_accounts': [
            'Income:LMTSD:Employer-Contribution',
            'Income:CapTech:Employer-Contribution'
        ]
    }"

CONFIG KEYS:
- destination_accounts: list of EXACT account names. PRIMARY way to specify
  destinations — no regex foot-guns, O(1) set lookup. When this key is provided
  with a non-empty list, the default destination_patterns are replaced (no
  silent regex fallback). Default: empty list `[]`.
- destination_patterns: list of regex patterns. A posting matches if its
  account string contains any pattern (re.search). Useful for automatic
  detection of accounts matching a naming convention. Default: HSA, 401k,
  IRA, DC (only applied when destination_accounts is not provided).
- counterparty_accounts: list of EXACT account names. A transaction qualifies
  only if some destination posting has another posting whose account is in
  this list. Default: the seven known contribution sources for this ledger.

A posting is treated as a destination if it matches destination_accounts OR
destination_patterns (union when both are provided). For best results use
destination_accounts (explicit, fast, no surprises) and reserve
destination_patterns for cases where you genuinely want convention-based
matching.

DEFAULTS:
    destination_accounts = ()
    destination_patterns = ('HSA', '401k', 'IRA', 'DC')
    counterparty_accounts = (
        'Equity:ZeroSumMatched:Transfers',
        'Assets:Banking:Checking:Joint-Ally-Spending',
        'Assets:Banking:Cash-Mgmt:Joint-Fidelity-Cash-Mgmt:Cash',
        'Assets:Banking:Cash-Mgmt:Tims-Fidelity-Cash-Mgmt:Cash',
        'Assets:Banking:Checking:Joint-BofA-Checking',
        'Income:LMTSD:Employer-Contribution',
        'Income:CapTech:Employer-Contribution',
    )

ACCOUNT VALIDATION:
When destination_accounts or counterparty_accounts is explicitly set in the
config (not just defaulted), each listed account is checked against Open
directives in the ledger. If any account has no matching Open directive
(neither itself nor any of its ancestor components), the plugin emits a
ParserError and refuses to load. This catches typos at load time instead of
silently failing to flag transactions.

Defaults are NOT validated — they're trusted. To get full validation, set
both keys explicitly (even if to the same values as defaults).

EXAMPLE:
The following transaction causes a load error:

    2026-01-15 * "Employer match"
        Assets:Retirement:401k:Cash               1000 USD
        Income:CapTech:Employer-Contribution     -1000 USD

Fix by adding contribution-year on the receiving posting:

    2026-01-15 * "Employer match"
        Assets:Retirement:401k:Cash               1000 USD
            contribution-year: "2026"
        Income:CapTech:Employer-Contribution     -1000 USD
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import ast
import logging
import re
from typing import Any, Tuple

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("missing_contribution_year",)

_DEFAULT_DESTINATION_ACCOUNTS: tuple[str, ...] = ()
_DEFAULT_DESTINATION_PATTERNS: tuple[str, ...] = ("HSA", "401k", "IRA", "DC")
_DEFAULT_COUNTERPARTY_ACCOUNTS: tuple[str, ...] = (
    "Equity:ZeroSumMatched:Transfers",
    "Assets:Banking:Checking:Joint-Ally-Spending",
    "Assets:Banking:Cash-Mgmt:Joint-Fidelity-Cash-Mgmt:Cash",
    "Assets:Banking:Cash-Mgmt:Tims-Fidelity-Cash-Mgmt:Cash",
    "Assets:Banking:Checking:Joint-BofA-Checking",
    "Income:LMTSD:Employer-Contribution",
    "Income:CapTech:Employer-Contribution",
)
_META_KEY: str = "contribution-year"

_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"destination_accounts", "destination_patterns", "counterparty_accounts"}
)


def _coerce_string_list(
    raw: Any,
    key_name: str,
    errors: list[ParserError],
) -> tuple[str, ...] | None:
    """Normalize a string-or-list value to a tuple, or None on type error.

    Appends a ParserError to `errors` and returns None if `raw` is neither a
    string nor a list of strings.
    """
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(p, str) for p in raw):
        return tuple(raw)
    errors.append(
        ParserError(
            source={"filename": "plugin config", "lineno": 0},
            message=(
                f"missing_contribution_year: '{key_name}' must be "
                f"a string or list of strings"
            ),
            entry=None,
        )
    )
    return None


def _parse_config(
    config: str | None,
) -> Tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], list[ParserError]]:
    """Parse inline Python-literal config and merge with defaults.

    Returns (destination_accounts, destination_patterns, counterparty_accounts,
    errors). Invalid syntax, unknown keys, or wrong-type values produce an
    error and the affected list falls back to defaults so the plugin still runs.
    """
    destination_accounts = _DEFAULT_DESTINATION_ACCOUNTS
    destination_patterns = _DEFAULT_DESTINATION_PATTERNS
    counterparty_accounts = _DEFAULT_COUNTERPARTY_ACCOUNTS
    errors: list[ParserError] = []

    if not config:
        return destination_accounts, destination_patterns, counterparty_accounts, errors

    try:
        cfg: dict[str, Any] = ast.literal_eval(config)
    except (ValueError, SyntaxError) as e:
        errors.append(
            ParserError(
                source={"filename": "plugin config", "lineno": 0},
                message=f"missing_contribution_year: Invalid config: {e}",
                entry=None,
            )
        )
        return destination_accounts, destination_patterns, counterparty_accounts, errors

    if not isinstance(cfg, dict):
        errors.append(
            ParserError(
                source={"filename": "plugin config", "lineno": 0},
                message=(
                    "missing_contribution_year: config must be a dict, "
                    f"got {type(cfg).__name__}"
                ),
                entry=None,
            )
        )
        return destination_accounts, destination_patterns, counterparty_accounts, errors

    unknown = set(cfg.keys()) - _ALLOWED_KEYS
    if unknown:
        errors.append(
            ParserError(
                source={"filename": "plugin config", "lineno": 0},
                message=(
                    f"missing_contribution_year: Unknown config keys: "
                    f"{', '.join(sorted(unknown))}. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_KEYS))}"
                ),
                entry=None,
            )
        )

    for key in (
        "destination_accounts",
        "destination_patterns",
        "counterparty_accounts",
    ):
        if key not in cfg:
            continue
        parsed = _coerce_string_list(cfg[key], key, errors)
        if parsed is None:
            continue
        if key == "destination_accounts":
            destination_accounts = parsed
        elif key == "destination_patterns":
            destination_patterns = parsed
        else:
            counterparty_accounts = parsed

    # Precedence rule: providing destination_accounts (non-empty) replaces the
    # default destination_patterns. Exact-match mode is opt-in to disable the
    # regex fallback — otherwise HSA-old would silently match the default 'HSA'
    # pattern. Explicit destination_patterns (including `[]`) is respected.
    if (
        "destination_accounts" in cfg
        and destination_accounts
        and "destination_patterns" not in cfg
    ):
        destination_patterns = ()

    return destination_accounts, destination_patterns, counterparty_accounts, errors


def _is_destination(
    account: str,
    destination_accounts: frozenset[str],
    destination_patterns: tuple[str, ...],
) -> bool:
    """True if account is in the exact-match set OR matches any regex pattern.

    Exact match is checked first (O(1) frozenset lookup) and short-circuits.
    Regex is only consulted when exact match fails.
    """
    if account in destination_accounts:
        return True
    return any(re.search(p, account) for p in destination_patterns)


def _opened_accounts(entries: data.Entries) -> frozenset[str]:
    """Return all accounts with an explicit Open directive."""
    return frozenset(e.account for e in entries if isinstance(e, data.Open))


def _is_account_valid(account: str, opened: frozenset[str]) -> bool:
    """True if the account (or any of its ancestor components) is opened.

    Beancount allows `open Assets:Bank` to implicitly open subaccounts like
    `Assets:Bank:Checking`, so we walk up the components and accept the first
    match.
    """
    if account in opened:
        return True
    parts = account.split(":")
    while len(parts) > 1:
        parts.pop()
        if ":".join(parts) in opened:
            return True
    return False


def _validate_accounts(
    config: str | None,
    destination_accounts: tuple[str, ...],
    counterparty_accounts: tuple[str, ...],
    entries: data.Entries,
) -> list[ParserError]:
    """Emit ParserErrors for any explicitly-configured account without an Open.

    Only accounts from keys the user explicitly set in the config are checked.
    Defaults are trusted (they're a known-good starting point for this project).

    Returns an empty list when:
    - No config was provided (using defaults)
    - Config couldn't be parsed (defaults will be used)
    - No account-list keys were set in the config
    - All listed accounts are valid
    """
    if not config:
        return []

    try:
        cfg = ast.literal_eval(config)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(cfg, dict):
        return []

    explicit_keys = set(cfg.keys()) & {
        "destination_accounts",
        "counterparty_accounts",
    }
    if not explicit_keys:
        return []

    opened = _opened_accounts(entries)
    errors: list[ParserError] = []

    for account in destination_accounts:
        if not _is_account_valid(account, opened):
            errors.append(
                ParserError(
                    source={"filename": "plugin config", "lineno": 0},
                    message=(
                        "missing_contribution_year: 'destination_accounts' "
                        f"references unknown account '{account}' "
                        "(no matching Open directive)"
                    ),
                    entry=None,
                )
            )

    for account in counterparty_accounts:
        if not _is_account_valid(account, opened):
            errors.append(
                ParserError(
                    source={"filename": "plugin config", "lineno": 0},
                    message=(
                        "missing_contribution_year: 'counterparty_accounts' "
                        f"references unknown account '{account}' "
                        "(no matching Open directive)"
                    ),
                    entry=None,
                )
            )

    return errors


def _missing_contribution_year_on(
    txn: data.Transaction,
    destination_accounts: frozenset[str],
    destination_patterns: tuple[str, ...],
    counterparty_set: frozenset[str],
) -> bool:
    """True iff txn has a qualifying destination posting whose meta lacks the year.

    A "qualifying destination" is a posting that:
      - matches destination_accounts or destination_patterns, AND
      - has at least one sibling posting whose account is in counterparty_set.

    For each qualifying destination, we check whether the posting itself
    carries `contribution-year` in its metadata. If any qualifying destination
    lacks that key, the transaction is flagged.
    """
    postings = txn.postings
    for idx, posting in enumerate(postings):
        if not _is_destination(
            posting.account, destination_accounts, destination_patterns
        ):
            continue
        other_accounts = {p.account for i, p in enumerate(postings) if i != idx}
        if not any(ca in other_accounts for ca in counterparty_set):
            continue
        # Qualifies as a contribution — does the receiving posting carry the year?
        if not (posting.meta and _META_KEY in posting.meta):
            return True
    return False


def missing_contribution_year(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, list[ParserError]]:
    """Emit ParserErrors for contributions missing contribution-year on the posting.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional inline Python-literal dict overriding
                destination_accounts, destination_patterns, and/or
                counterparty_accounts

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    (
        destination_accounts,
        destination_patterns,
        counterparty_accounts,
        config_errors,
    ) = _parse_config(config)
    errors: list[ParserError] = list(config_errors)

    errors.extend(
        _validate_accounts(config, destination_accounts, counterparty_accounts, entries)
    )

    if errors:
        return entries, errors

    destination_accounts_set = frozenset(destination_accounts)
    counterparty_set = frozenset(counterparty_accounts)

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        if _missing_contribution_year_on(
            entry, destination_accounts_set, destination_patterns, counterparty_set
        ):
            errors.append(
                ParserError(
                    source={
                        "filename": entry.meta.get("filename", "unknown"),
                        "lineno": entry.meta.get("lineno", 0),
                    },
                    message=(
                        f"Contribution missing '{_META_KEY}' on the receiving "
                        f"posting: {entry.narration}"
                    ),
                    entry=None,
                )
            )

    if len(errors) > len(config_errors):
        logger.warning(
            "missing_contribution_year: %d contribution(s) missing %s",
            len(errors) - len(config_errors),
            _META_KEY,
        )

    return entries, errors
