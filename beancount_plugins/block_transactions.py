#!/usr/bin/env python3
"""Beancount plugin to block transactions on explicitly opened accounts.

Some accounts exist only as attachment points for documents (via Fava) and must
never carry transactions themselves. A common example is an investment parent
account such as `Assets:Investment:Brokerage`: you want to attach statements to
it, but actual holdings live in sub-accounts like
`Assets:Investment:Brokerage:USD` or `Assets:Investment:Brokerage:VOO`.

Normally Beancount would reject an Open directive for an account that only
groups other accounts... but opening the parent is exactly what lets Fava
attach documents to it. This plugin lets you open the parent explicitly while
guaranteeing no transaction ever posts to it.

WHAT IT DOES:
- Identifies accounts marked as 'block-transactions' in their Open directives
- Flags any posting whose account is EXACTLY a blocked account
- Reports violations as parser errors with proper file/line references
- Integrates seamlessly with bean-check for validation pipelines

USAGE:
In your main ledger file:
    plugin "beancount_plugins.block_transactions"

ACCOUNT CONFIGURATION:
Mark an account as transaction-blocked by adding metadata to its Open directive:

    2024-01-01 open Assets:Investment:Brokerage
        block-transactions: TRUE

Any transaction posting directly to `Assets:Investment:Brokerage` will be
flagged. Sub-accounts (`Assets:Investment:Brokerage:USD`) are unaffected because
matching is exact — the metadata applies only to the account that declares it.

HOW IT WORKS:
1. Phase 1 (Index): Scans all Open directives
   - Collects accounts with 'block-transactions: True' metadata
2. Phase 2 (Validate): Processes transactions
   - Checks each posting against the blocked-account set (O(1) exact match)
   - Reports ParserErrors for postings to blocked accounts

ERROR REPORTING:
Errors are reported as ParserErrors with proper file/line information,
so they appear in bean-check output and IDE error panels with navigation:

    your-file.bean:42: Posting to transaction-blocked account
    'Assets:Investment:Brokerage': "Transfer to brokerage"

The default is to NOT block transactions; only accounts whose Open directive
sets `block-transactions: TRUE` are enforced.
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from typing import List, Tuple

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("block_transactions",)


def block_transactions(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Flag postings to accounts whose Open directive blocks transactions.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (unused)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors: list[ParserError] = []

    # Single pass: collect blocked accounts from Open directives (which always
    # precede Transactions in Beancount's sorted entry list), then validate
    # transactions. Matching is exact, so sub-accounts are unaffected.
    blocked_accounts: set[str] = set()
    violations_count = 0

    for entry in entries:
        if isinstance(entry, data.Open):
            if entry.meta and entry.meta.get("block-transactions") is True:
                blocked_accounts.add(entry.account)
        elif isinstance(entry, data.Transaction):
            for posting in entry.postings:
                if posting.account in blocked_accounts:
                    violations_count += 1
                    errors.append(
                        ParserError(
                            source={
                                "filename": entry.meta.get("filename", "unknown"),
                                "lineno": entry.meta.get("lineno", 0),
                            },
                            message=(
                                f"Posting to transaction-blocked account "
                                f"'{posting.account}': {entry.narration}"
                            ),
                            entry=None,
                        )
                    )

    logger.debug(
        "block_transactions: found %d accounts blocking transactions",
        len(blocked_accounts),
    )

    if violations_count > 0:
        logger.warning(
            "block_transactions: %d posting(s) to transaction-blocked accounts",
            violations_count,
        )

    return entries, errors
