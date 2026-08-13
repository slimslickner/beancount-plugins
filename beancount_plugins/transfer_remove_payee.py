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
- Tags matched transactions with #transfer-remove-payee
- Changes the transaction flag to '!' so bean-check surfaces it for review

USAGE:
In your main ledger file (load BEFORE check_valid_tags so the new tag is allowed):

    plugin "beancount_plugins.transfer_remove_payee"
    plugin "beancount_plugins.check_valid_tags" "tags.yaml"

If you also use check_valid_tags, add the tag to your tags.yaml:

    tags:
      transfer-remove-payee:
        label: "Transaction looks like a transfer but has a payee — review and remove payee"

EXAMPLE:
Before:

    2026-01-15 * "Bank A" "Transfer to brokerage"
        Assets:Checking            -1000 USD
        Assets:Investment:Brokerage  1000 USD

After:

    2026-01-15 ! "Bank A" "Transfer to brokerage" #transfer-remove-payee
        Assets:Checking            -1000 USD
        Assets:Investment:Brokerage  1000 USD

NON-MATCHES (intentionally left alone):
- Transactions with no payee
- Transactions involving Expenses: or Income: accounts
- Transactions involving Assets:Receivable: (AR accounts use payees for invoices)
- Transactions where all postings share the same immediate parent
  (e.g. Assets:Checking <-> Assets:Savings — narration is enough, no payee needed)
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
_TAG_NAME: str = "transfer-remove-payee"
_PENDING_FLAG: str = "!"


def _is_transfer_like(account: str) -> bool:
    return any(account.startswith(pfx) for pfx in _TRANSFER_PREFIXES)


def transfer_remove_payee(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Flag and tag transactions that look like transfers but carry a payee.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (unused)

    Returns:
        Tuple of (modified_entries, errors)
    """
    errors: list[ParserError] = []
    new_entries: list[data.Directive] = []
    flagged_count = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            new_entries.append(entry)
            continue

        # Must have a payee to be a candidate.
        if not entry.payee:
            new_entries.append(entry)
            continue

        accounts = [p.account for p in entry.postings]

        # All postings must be on transfer-like accounts.
        if not all(_is_transfer_like(a) for a in accounts):
            new_entries.append(entry)
            continue

        # AR accounts legitimately use payees (invoices).
        if any(a.startswith(_RECEIVABLE_PREFIX) for a in accounts):
            new_entries.append(entry)
            continue

        # Distinct immediate parents (drop last segment). Same-parent means
        # postings are siblings within one branch (e.g. Checking <-> Savings).
        parents = {":".join(a.split(":")[:-1]) for a in accounts}
        if len(parents) <= 1:
            new_entries.append(entry)
            continue

        new_tags = (entry.tags or frozenset()) | frozenset({_TAG_NAME})
        new_entry = entry._replace(flag=_PENDING_FLAG, tags=new_tags)
        new_entries.append(new_entry)
        flagged_count += 1

    logger.debug(
        "transfer_remove_payee: flagged %d transfer(s) with payee", flagged_count
    )

    return new_entries, errors
