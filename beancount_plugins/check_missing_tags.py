#!/usr/bin/env python3
"""Beancount plugin to validate that transactions have required tags.

This plugin enforces tagging policies by checking that transactions posting to
certain accounts have tags defined. It's useful for tracking transaction categories,
ensuring accountability, or separating different types of transactions.

WHAT IT DOES:
- Identifies accounts marked as 'tag-expected' in their Open directives
- Validates that any transaction posting to these accounts includes tags
- Reports violations as parser errors with proper file/line references
- Integrates seamlessly with bean-check for validation pipelines

USAGE:
In your main ledger file:
    plugin "beancount_plugins.check_missing_tags"

Optional config (for future enhancements):
    plugin "beancount_plugins.check_missing_tags" "strict"

ACCOUNT CONFIGURATION:
Mark accounts that require tags by adding metadata to their Open directive:

    2024-01-01 open Expenses:Travel
        meta: "tag-expected: True"

or in the account bean file:

    2024-01-01 open Liabilities:Credit-Cards:My-Card
        tag-expected: True

Any transaction posting to this account without tags will be flagged as an error.

HOW IT WORKS:
1. Phase 1 (Index): Scans all Open directives
   - Collects accounts with 'tag-expected: True' metadata
2. Phase 2 (Validate): Processes transactions
   - Checks if transaction has tags (via #tag syntax in narration)
   - For untagged transactions, checks each posting
   - Reports ParserErrors for postings to tag-required accounts

ERROR REPORTING:
Errors are reported as ParserErrors with proper file/line information,
so they appear in bean-check output and IDE error panels with navigation:

    your-file.bean:42: Posting to tag-required account 'Liabilities:My-Card'
    missing tags: "Purchase at store"

WHY TAGS MATTER:
- Categorize transactions beyond the account hierarchy
- Track recurring vs. one-time expenses
- Organize travel expenses, medical costs, project work, etc.
- Easy to query and analyze via bean-query or Fava

EXAMPLES OF TAG USAGE:
With tag-required accounts, you'd write transactions like:

    2026-01-15 * "Flight booking" #travel
        Liabilities:Credit-Cards:My-Card  -500 USD
        Expenses:Travel:Flights

    2026-01-20 * "Pharmacy" #medical
        Liabilities:Credit-Cards:My-Card  -50 USD
        Expenses:Health-Medical

Tags help organize and filter transactions for reporting and analysis.
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from typing import List, Tuple

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_missing_tags",)


def check_missing_tags(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Flag postings to tag-required accounts that lack tags.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (for future enhancements)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors = []

    # Phase 1: Build index of accounts requiring tags
    tag_required_accounts = set()
    for entry in entries:
        if isinstance(entry, data.Open):
            # Check if the account has tag-expected metadata set to True
            if entry.meta and entry.meta.get("tag-expected") is True:
                tag_required_accounts.add(entry.account)

    logger.info(f"Found {len(tag_required_accounts)} accounts requiring tags")

    # Phase 2: Process transactions and generate errors for violations
    violations_count = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Check if transaction has tags
        has_tags = bool(entry.tags)

        if has_tags:
            # Transaction has tags, no violations possible
            continue

        # Transaction lacks tags - check postings for violations
        for posting in entry.postings:
            if posting.account in tag_required_accounts:
                # Violation found - create error
                violations_count += 1

                # Create error with proper location information
                error = ParserError(
                    source={
                        "filename": entry.meta.get("filename", "unknown"),
                        "lineno": entry.meta.get("lineno", 0),
                    },
                    message=(
                        f"Posting to tag-required account '{posting.account}' "
                        f"missing tags: {entry.narration}"
                    ),
                    entry=None,
                )
                errors.append(error)

    # Log summary
    if violations_count > 0:
        logger.warning(
            f"Found {violations_count} postings to tag-required accounts without tags"
        )
    else:
        logger.info("All postings to tag-required accounts are properly tagged")

    return entries, errors
