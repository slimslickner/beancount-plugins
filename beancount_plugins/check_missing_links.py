#!/usr/bin/env python3
"""Beancount plugin to validate that transactions have required links.

This plugin enforces linking policies by checking that transactions posting to
certain accounts include at least one link (^link-name). It's useful for
accounts receivable, reimbursable expenses, or any account where you want
every transaction traceable to an external reference.

WHAT IT DOES:
- Identifies accounts marked as 'link-expected' in their Open directives
- Validates that any transaction posting to these accounts includes links
- Reports violations as parser errors with proper file/line references
- Integrates seamlessly with bean-check for validation pipelines

USAGE:
In your main ledger file:
    plugin "beancount_plugins.check_missing_links"

ACCOUNT CONFIGURATION:
Mark accounts that require links by adding metadata to their Open directive:

    2024-01-01 open Assets:AccountsReceivable
        link-expected: True

    2024-01-01 open Expenses:Reimbursable
        link-expected: True

Any transaction posting to these accounts without a link will be flagged.

HOW IT WORKS:
1. Phase 1 (Index): Scans all Open directives
   - Collects accounts with 'link-expected: True' metadata
2. Phase 2 (Validate): Processes transactions
   - Checks if transaction has links (via ^link-name syntax)
   - For unlinked transactions, checks each posting
   - Reports ParserErrors for postings to link-required accounts

ERROR REPORTING:
Errors are reported as ParserErrors with proper file/line information,
so they appear in bean-check output and IDE error panels with navigation:

    your-file.bean:42: Posting to link-required account 'Assets:AR:Client-A'
    missing link: "Invoice payment"

EXAMPLES OF LINK USAGE:
With link-required accounts, you'd write transactions like:

    2026-01-15 * "Invoice payment" ^inv-2026-001
        Assets:AccountsReceivable  -500 USD
        Assets:Checking             500 USD

    2026-01-20 * "Reimbursement" ^receipt-42
        Expenses:Reimbursable  75 USD
        Liabilities:CreditCard  -75 USD

Links provide a traceable reference to external documents (invoices, receipts,
tickets) and enable cross-referencing transactions in Fava and bean-query.
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from typing import List, Tuple

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_missing_links",)


def check_missing_links(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Flag postings to link-required accounts that lack links.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (unused, reserved for future enhancements)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors: list[ParserError] = []

    # Single pass: collect link-required accounts from Open directives (which always
    # precede Transactions in Beancount's sorted entry list), then validate transactions.
    link_required_accounts: set[str] = set()
    violations_count = 0

    for entry in entries:
        if isinstance(entry, data.Open):
            if entry.meta and entry.meta.get("link-expected") is True:
                link_required_accounts.add(entry.account)
        elif isinstance(entry, data.Transaction):
            if entry.links:
                continue
            for posting in entry.postings:
                if posting.account in link_required_accounts:
                    violations_count += 1
                    errors.append(
                        ParserError(
                            source={
                                "filename": entry.meta.get("filename", "unknown"),
                                "lineno": entry.meta.get("lineno", 0),
                            },
                            message=(
                                f"Posting to link-required account '{posting.account}' "
                                f"missing link: {entry.narration}"
                            ),
                            entry=None,
                        )
                    )

    logger.debug("Found %d accounts requiring links", len(link_required_accounts))

    if violations_count > 0:
        logger.warning(
            "Found %d postings to link-required accounts without links",
            violations_count,
        )
    else:
        logger.debug("All postings to link-required accounts have links")

    return entries, errors
