#!/usr/bin/env python3
"""Beancount plugin to flag transfer transactions that incorrectly have a payee.

Pure-transfer transactions (between Assets:, Liabilities:, or Equity: accounts)
should describe their purpose in the narration, not in the payee field. The payee
field is reserved for actual counterparties — vendors, customers, employers.
Setting a payee on a transfer is almost always a mistake (e.g. an import from a
bank that incorrectly identified a transfer as a purchase).

WHAT IT DOES:
- Identifies transactions that match ALL of these criteria:
  - Have a payee set (non-empty)
  - All postings are to Assets:, Liabilities:, or Equity: accounts
  - No posting is to an Assets:Receivable: account (AR legitimately uses payees)
  - Postings span at least two distinct immediate parents (i.e., actually cross
    account boundaries — e.g. Assets:Checking -> Assets:Investment:Brokerage)
- Emits a ParserError for each violation with the transaction's file/line, so
  bean-check surfaces it and the ledger fails to load until fixed.

USAGE:
In your main ledger file:

    plugin "beancount_plugins.transfer_remove_payee"

NON-MATCHES (intentionally left alone):
- Transactions with no payee
- Transactions involving Expenses: or Income: accounts
- Transactions involving Assets:Receivable: (AR accounts use payees for invoices)
- Transactions where all postings share the same immediate parent
  (e.g. Assets:Checking <-> Assets:Savings — narration is enough, no payee needed)

EXAMPLE:
The following transaction causes a load error:

    2026-01-15 * "Bank A" "Transfer to brokerage"
        Assets:Checking            -1000 USD
        Assets:Investment:Brokerage  1000 USD

Fix by removing the payee:

    2026-01-15 * "Transfer to brokerage"
        Assets:Checking            -1000 USD
        Assets:Investment:Brokerage  1000 USD
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from typing import List, Tuple

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("transfer_remove_payee",)

_TRANSFER_PREFIXES: tuple[str, ...] = ("Assets:", "Liabilities:", "Equity:")
_RECEIVABLE_PREFIX: str = "Assets:Receivable:"


def _is_transfer_like(account: str) -> bool:
    return any(account.startswith(pfx) for pfx in _TRANSFER_PREFIXES)


def transfer_remove_payee(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Report transfer transactions that incorrectly carry a payee.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (unused)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors: list[ParserError] = []

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Must have a payee to be a candidate.
        if not entry.payee:
            continue

        accounts = [p.account for p in entry.postings]

        # All postings must be on transfer-like accounts.
        if not all(_is_transfer_like(a) for a in accounts):
            continue

        # AR accounts legitimately use payees (invoices).
        if any(a.startswith(_RECEIVABLE_PREFIX) for a in accounts):
            continue

        # Distinct immediate parents (drop last segment). Same-parent means
        # postings are siblings within one branch (e.g. Checking <-> Savings).
        parents = {":".join(a.split(":")[:-1]) for a in accounts}
        if len(parents) <= 1:
            continue

        errors.append(
            ParserError(
                source={
                    "filename": entry.meta.get("filename", "unknown"),
                    "lineno": entry.meta.get("lineno", 0),
                },
                message=(
                    f"Transfer transaction has a payee — remove it "
                    f"(transfers should use narration only): {entry.narration}"
                ),
                entry=None,
            )
        )

    if errors:
        logger.warning(
            "transfer_remove_payee: %d transfer(s) carry a payee", len(errors)
        )

    return entries, errors
