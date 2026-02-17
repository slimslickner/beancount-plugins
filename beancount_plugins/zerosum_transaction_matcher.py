"""Beancount plugin for matching transfer counterparties.

This plugin automatically identifies transfers between accounts and matches them
with their counterparties, adding comprehensive metadata to Equity:ZeroSum postings.
It's designed to work with Beancount's built-in zerosum plugin to handle multi-account
transfers efficiently.

WHAT IT DOES:
- Identifies transfer postings (Assets/Liabilities to Assets/Liabilities)
- Matches transfers across ZeroSum links (created by the zerosum plugin)
- Matches direct transfers within the same transaction
- Adds metadata to track counterparty information
- Adds descriptive narration as posting metadata (e.g., "Transfer from Checking to Savings")

USAGE:
In your main ledger file:
    plugin "beancount_plugins.zerosum_transaction_matcher"

Optional configuration to warn about unmatched transfers:
    plugin "beancount_plugins.zerosum_transaction_matcher" "include_unmatched_warnings"

HOW IT WORKS:
1. Phase 1 (Fast): Builds an O(1) lookup index of all transfers
   - Indexes ZeroSum links from the zerosum plugin
   - Indexes direct transfers (multiple Assets/Liabilities in same transaction)
2. Phase 2: Processes transactions and adds metadata to matched transfers
   - For each Equity:ZeroSum posting, finds its matched counterparty
   - Uses match_id when available (for split transfers with multiple counterparties)
   - Falls back to first Assets/Liabilities posting

METADATA ADDED:
The plugin adds the following metadata to Equity:ZeroSum postings:
    source_account: The source Assets/Liabilities account
    matched_transfer_account: The matched counterparty account
    matched_transfer_date: Date of the transfer
    narration: Human-readable transfer description (e.g., "Transfer from Checking to Savings")
               If existing narration metadata is present, it's appended in parentheses

Example on a transfer from Checking to Savings:
    Equity:ZeroSum:Transfers 500 USD
        source_account: "Assets:Banking:Checking:My-Checking"
        matched_transfer_account: "Assets:Savings:My-Savings"
        matched_transfer_date: "2026-02-05"
        narration: "Transfer from My-Checking to My-Savings"

PERFORMANCE:
O(n) where n = number of transactions (single index-building pass)
Instead of: O(n*k) where k = average database queries per posting

WHY THIS MATTERS:
- Transfer matching is essential for reconciliation and balance validation
- The zerosum plugin creates placeholder Equity:ZeroSum postings for transfers
- This plugin enriches those postings with matching data for downstream use
- Fast O(1) lookups make this suitable for use in Fava dashboards
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from typing import Tuple

from beancount.core import data

logger = logging.getLogger(__name__)

__plugins__ = ("zerosum_transaction_matcher",)


def _get_leaf_account(account: str) -> str:
    """Extract the leaf (last segment) of an account name.

    Useful for generating human-readable narrations without the full account path.

    Args:
        account: Full account path (e.g., "Assets:Banking:Checking:Joint-Ally-Spending")

    Returns:
        Leaf account name (e.g., "Spending")

    Example:
        >>> _get_leaf_account("Assets:Banking:Checking:Joint-Ally-Spending")
        "Spending"
    """
    return account.split(":")[-1]


def _generate_transfer_narration(
    source_account: str, matched_account: str, source_amount
) -> str:
    """Generate a human-readable transfer narration based on money flow.

    Uses the sign of the amount to determine direction:
    - Negative amount = money leaving source account = "from" source "to" matched
    - Positive amount = money entering source account = "from" matched "to" source

    This allows the narration to accurately reflect which account is sending
    money and which is receiving, regardless of posting order.

    Args:
        source_account: The primary account in the transfer posting
        matched_account: The matched counterparty account
        source_amount: The amount in the source account (Decimal, can be negative)

    Returns:
        Human-readable narration (e.g., "Transfer from Checking to Savings")

    Example:
        >>> _generate_transfer_narration(
        ...     "Assets:Banking:Checking:Main",
        ...     "Assets:Savings:Emergency",
        ...     Decimal("-500")
        ... )
        "Transfer from Main to Emergency"
    """
    source_leaf = _get_leaf_account(source_account)
    matched_leaf = _get_leaf_account(matched_account)

    # Negative amount = money leaving source account = sending
    # Positive amount = money entering source account = receiving
    if source_amount < 0:
        return f"Transfer from {source_leaf} to {matched_leaf}"
    else:
        return f"Transfer from {matched_leaf} to {source_leaf}"


def zerosum_transaction_matcher(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, list[str]]:
    """Match transfer postings to their counterparty accounts.

    Builds an index of all transfers for O(1) lookups instead of querying
    for each posting. This makes the plugin fast enough for Fava page loads.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config string (e.g., "include_unmatched_warnings")

    Returns:
        Tuple of (entries_with_metadata, errors)
    """
    errors = []
    warn_unmatched = config and "include_unmatched_warnings" in config.lower()

    # PHASE 1: Build indexes (single pass through entries)
    logger.debug("Building transfer indexes...")

    # ZeroSum index: link -> list of (account, date, payee, txn)
    zerosum_index = {}

    # Direct transfer index: (txn_id, account) -> (counterparty_account, date, payee)
    direct_transfer_index = {}

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        txn_id = entry.meta.get("id")

        # Extract all Assets/Liabilities postings in this transaction
        transfer_postings = [
            p
            for p in entry.postings
            if p.account
            and (p.account.startswith("Assets") or p.account.startswith("Liabilities"))
            and p.units  # Has amount (not balancing posting)
        ]

        if not transfer_postings:
            continue

        # Index ZeroSum links
        if entry.links:
            for link in entry.links:
                if link.startswith("ZeroSum."):
                    if link not in zerosum_index:
                        zerosum_index[link] = []
                    for posting in transfer_postings:
                        zerosum_index[link].append(
                            {
                                "account": posting.account,
                                "date": entry.date,
                                "payee": entry.payee,
                            }
                        )

        # Index direct transfers (same transaction, different accounts)
        if len(transfer_postings) >= 2 and txn_id:
            for posting in transfer_postings:
                # Find other Assets/Liabilities in same transaction
                other_postings = [
                    p for p in transfer_postings if p.account != posting.account
                ]
                if other_postings:
                    key = (txn_id, posting.account)
                    # Use first counterparty found
                    counterparty = other_postings[0].account
                    direct_transfer_index[key] = {
                        "account": counterparty,
                        "date": entry.date,
                        "payee": entry.payee,
                    }

    logger.debug(
        f"Transfer indexes built: {len(zerosum_index)} ZeroSum links, "
        f"{len(direct_transfer_index)} direct transfer pairs"
    )

    # PHASE 2: Process entries and add metadata using indexes
    new_entries = []
    transfer_postings_checked = 0
    transfer_postings_matched = 0
    transfer_postings_unmatched = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            new_entries.append(entry)
            continue

        # Check if any postings are transfers
        has_transfers = any(_is_transfer_posting(posting) for posting in entry.postings)

        if not has_transfers:
            new_entries.append(entry)
            continue

        # Process transfer postings
        # First pass: find all transfer postings and their matches
        new_postings = []
        txn_id = entry.meta.get("id")

        # Build map of matched accounts for each transfer posting
        transfer_matches = {}  # account -> matched_account
        transfer_amounts = {}  # account -> amount for narration generation
        for posting in entry.postings:
            if not _is_transfer_posting(posting):
                continue

            transfer_postings_checked += 1
            matched_account = None

            # 1. Try ZeroSum match first
            if entry.links:
                for link in entry.links:
                    if link.startswith("ZeroSum.") and link in zerosum_index:
                        candidates = zerosum_index[link]
                        # Find counterparty that's not this account
                        for candidate in candidates:
                            if candidate["account"] != posting.account:
                                matched_account = candidate["account"]
                                logger.debug(
                                    f"ZeroSum match: {posting.account} -> {matched_account}"
                                )
                                break
                        if matched_account:
                            break

            # 2. Try direct transfer match
            if not matched_account and txn_id:
                key = (txn_id, posting.account)
                if key in direct_transfer_index:
                    matched = direct_transfer_index[key]
                    matched_account = matched["account"]
                    logger.debug(
                        f"Direct transfer match: {posting.account} -> {matched_account}"
                    )

            if matched_account:
                transfer_postings_matched += 1
                transfer_matches[posting.account] = matched_account
                # Track the amount for narration generation
                if posting.units:
                    transfer_amounts[posting.account] = posting.units.number
            else:
                transfer_postings_unmatched += 1
                if warn_unmatched:
                    logger.warning(
                        f"Transfer not matched: {posting.account} on {entry.date} ({entry.narration})"
                    )
                else:
                    logger.debug(
                        f"Transfer not matched: {posting.account} on {entry.date} ({entry.narration})"
                    )

        # Second pass: add metadata to Equity:ZeroSum postings
        # For transactions with multiple Equity:ZeroSum postings (split transfers),
        # match each Equity posting to its corresponding counterparty using
        # the match_id to look up the correct account in the zerosum_index
        for posting in entry.postings:
            # If this is a ZeroSum equity posting, add metadata from matched transfer
            if posting.account and posting.account.startswith("Equity:ZeroSum"):
                matched_account = None
                matched_date = None
                source_account = None

                # Find the source Assets/Liabilities posting in THIS transaction
                for src_posting in entry.postings:
                    if _is_transfer_posting(src_posting):
                        source_account = src_posting.account
                        break

                # Strategy 1: Use match_id to find counterparty from OTHER transaction
                # Each Equity:ZeroSum posting has a match_id that corresponds to
                # a ZeroSum link. Look up that link in zerosum_index to find the
                # counterparty account from the matched transaction.
                if posting.meta and "match_id" in posting.meta:
                    match_id = posting.meta["match_id"]
                    link_key = f"ZeroSum.{match_id}"
                    if link_key in zerosum_index:
                        candidates = zerosum_index[link_key]
                        # Find the account that's NOT the source account
                        # (i.e., the account from the OTHER transaction)
                        for candidate in candidates:
                            if candidate["account"] != source_account:
                                matched_account = candidate["account"]
                                matched_date = candidate["date"]
                                logger.debug(
                                    f"Match by ID: {posting.account} -> {matched_account} (link: {link_key})"
                                )
                                break

                # Strategy 2: Fallback to direct transfer match if no match_id
                if not matched_account:
                    for transfer_posting in entry.postings:
                        if (
                            _is_transfer_posting(transfer_posting)
                            and transfer_posting.account in transfer_matches
                        ):
                            matched_account = transfer_matches[transfer_posting.account]
                            matched_date = entry.date
                            logger.debug(
                                f"Fallback match: {posting.account} -> {matched_account}"
                            )
                            break

                if matched_account and source_account:
                    new_meta = dict(posting.meta) if posting.meta else {}

                    # Preserve existing narration metadata if present
                    existing_narration = new_meta.get("narration")

                    new_meta["source_account"] = source_account
                    new_meta["matched_transfer_account"] = matched_account
                    new_meta["matched_transfer_date"] = (
                        str(matched_date) if matched_date else str(entry.date)
                    )

                    # Generate narration for this posting and add as metadata
                    source_amount = transfer_amounts.get(source_account)
                    if source_amount is not None:
                        narration = _generate_transfer_narration(
                            source_account, matched_account, source_amount
                        )
                        # If there was existing narration, append it in parentheses
                        if existing_narration:
                            narration = f"{narration} ({existing_narration})"
                        new_meta["narration"] = narration

                    new_posting = posting._replace(meta=new_meta if new_meta else None)
                    new_postings.append(new_posting)
                else:
                    new_postings.append(posting)
            else:
                # Non-ZeroSum postings pass through unchanged
                new_postings.append(posting)

        # Create new transaction with updated postings (keep original narration)
        new_txn = entry._replace(postings=new_postings)
        new_entries.append(new_txn)

    # Log summary
    logger.info(
        f"Transfer matching complete: {transfer_postings_matched} matched, "
        f"{transfer_postings_unmatched} unmatched out of {transfer_postings_checked} transfers"
    )

    return new_entries, errors


def _is_transfer_posting(posting: data.Posting) -> bool:
    """Check if a posting represents a transfer between accounts.

    A transfer posting is identified by:
    - Account is Assets or Liabilities (not Expenses, Income, or Equity)
    - The posting has units/amount (not a balancing posting with missing amount)

    Transfer postings are the key accounts involved in account-to-account transfers.
    Expense/Income postings and balancing postings are excluded.

    Args:
        posting: A beancount posting to check

    Returns:
        True if this posting represents a transfer between accounts

    Example:
        >>> posting1 = Posting("Assets:Checking", Amount(Decimal("-500"), "USD"), ...)
        >>> _is_transfer_posting(posting1)
        True

        >>> posting2 = Posting("Expenses:Utilities", Amount(Decimal("100"), "USD"), ...)
        >>> _is_transfer_posting(posting2)
        False
    """
    if not posting.account:
        return False

    if not posting.units:
        # Balancing posting, not a transfer
        return False

    # Check if account is Assets or Liabilities
    return posting.account.startswith("Assets") or posting.account.startswith(
        "Liabilities"
    )
