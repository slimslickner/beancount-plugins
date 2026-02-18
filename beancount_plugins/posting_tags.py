#!/usr/bin/env python3
"""Beancount plugin to promote posting-level tags to the transaction level.

Beancount only supports #tag syntax at the transaction level. All postings in a
transaction inherit the same tags, which is incorrect for split-purpose transactions
(e.g., a Costco trip with furniture for #123MainSt and a gift for #Jim). This plugin
adds per-posting tag granularity while keeping tags visible/searchable at the
transaction level in tools like Fava.

WHAT IT DOES:
- Scans transactions for postings with a 'tags' metadata key
- Parses the space-separated tag string into individual tags
- Promotes posting tags to the transaction level (union with existing tags)
- Preserves the 'tags' metadata on each posting for per-posting association

USAGE:
In your main ledger file (load BEFORE tag validation plugins):
    plugin "beancount_plugins.posting_tags"
    plugin "beancount_plugins.check_missing_tags"
    plugin "beancount_plugins.check_valid_tags"

POSTING TAG SYNTAX:
Add a 'tags' metadata key to postings with space-separated tag names (no # prefix):

    2026-01-15 * "Costco"
        Expenses:Furniture  200 USD
            tags: "123MainSt"
        Expenses:Gifts  50 USD
            tags: "Jim"
        Assets:Checking  -250 USD

After plugin processing, the transaction becomes:

    2026-01-15 * "Costco" #123MainSt #Jim
        Expenses:Furniture  200 USD
            tags: "123MainSt"
        Expenses:Gifts  50 USD
            tags: "Jim"
        Assets:Checking  -250 USD

Tags are now searchable at the transaction level via Fava and bean-query, and the
posting metadata preserves which posting each tag belongs to.

MULTIPLE TAGS PER POSTING:
Use space-separated tag names:

    2026-01-15 * "Home Depot"
        Expenses:Home-Improvement  300 USD
            tags: "123MainSt renovation"

ERROR REPORTING:
Reports ParserErrors for non-string 'tags' metadata values.
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from typing import List, Tuple

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("posting_tags",)


def posting_tags(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Promote posting-level tags to the transaction level.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (unused)

    Returns:
        Tuple of (modified_entries, errors)
    """
    errors: list[ParserError] = []
    new_entries: list[data.Directive] = []

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            new_entries.append(entry)
            continue

        # Collect tags from all postings
        posting_tags: set[str] = set()
        has_posting_tags = False

        for posting in entry.postings:
            if posting.meta and "tags" in posting.meta:
                has_posting_tags = True
                raw = posting.meta["tags"]

                if not isinstance(raw, str):
                    error = ParserError(
                        source={
                            "filename": entry.meta.get("filename", "unknown"),
                            "lineno": entry.meta.get("lineno", 0),
                        },
                        message=(
                            f"Posting 'tags' metadata must be a string, "
                            f"got {type(raw).__name__}: {entry.narration}"
                        ),
                        entry=None,
                    )
                    errors.append(error)
                    continue

                tags = raw.split()
                posting_tags.update(tags)

        if has_posting_tags and posting_tags:
            # Promote: union of existing transaction tags + posting tags
            new_tags = (entry.tags or frozenset()) | frozenset(posting_tags)
            entry = entry._replace(tags=new_tags)

        new_entries.append(entry)

    promoted_count = sum(
        1
        for e in new_entries
        if isinstance(e, data.Transaction)
        and any(p.meta and "tags" in p.meta for p in e.postings)
    )
    logger.info(f"Promoted posting tags on {promoted_count} transactions")

    return new_entries, errors
