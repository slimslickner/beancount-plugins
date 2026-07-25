"""Synthesizes Price directives for postings with a price annotation, or for
augmenting postings with a cost annotation -- same behavior as
beancount.plugins.implicit_prices, except that a posting can opt out of
cost-based price synthesis by setting metadata:

    Assets:Brokerage:NewFirm:GOOG   1 GOOG {170.00 USD, 2025-02-01}
        no-implicit-price: TRUE

This is meant for cases like in-kind transfers, where the cost basis of the
incoming lot is not today's market price and shouldn't be recorded as one.

Use this INSTEAD of beancount.plugins.implicit_prices, not alongside it --
running both will just re-add the prices this one skips.
"""

import collections

from beancount.core import amount
from beancount.core import data
from beancount.core import inventory
from beancount.core.data import Transaction

__plugins__ = ("add_implicit_prices_flagged",)

ImplicitPriceError = collections.namedtuple(
    "ImplicitPriceError", "source message entry"
)

METADATA_FIELD = "__implicit_prices__"
SKIP_FIELD = "no-implicit-price"


def add_implicit_prices_flagged(entries, unused_options_map):
    """Insert implicitly defined prices from Transactions, honoring a
    per-posting opt-out flag for cost-derived prices.

    Args:
      entries: A list of directives. We're interested only in the Transaction
        instances.
      unused_options_map: A parser options dict.

    Returns:
      A list of entries, possibly with more Price entries than before, and a
      list of errors.
    """
    new_entries = []
    errors = []

    # A dict of (date, currency, number, cost-currency) to price entry.
    new_price_entry_map = {}
    balances = collections.defaultdict(inventory.Inventory)

    for entry in entries:
        # Always replicate the existing entries.
        new_entries.append(entry)

        if isinstance(entry, Transaction):
            for posting in entry.postings:
                units = posting.units
                cost = posting.cost

                # Check if the position is matching against an existing
                # position.
                _, booking = balances[posting.account].add_position(posting)

                if posting.price is not None:
                    # Explicit price annotation, e.g.
                    #   Assets:Account 100 USD @ 1.10 CAD
                    meta = data.new_metadata(
                        entry.meta["filename"], entry.meta["lineno"]
                    )
                    meta[METADATA_FIELD] = "from_price"
                    price_entry = data.Price(
                        meta, entry.date, units.currency, posting.price
                    )

                elif cost is not None and booking != inventory.MatchResult.REDUCED:
                    # Cost-derived price, e.g.
                    #   Assets:Account 100 HOOL {564.20}
                    # Skip if the posting is flagged to opt out.
                    if posting.meta and posting.meta.get(SKIP_FIELD):
                        price_entry = None
                    else:
                        meta = data.new_metadata(
                            entry.meta["filename"], entry.meta["lineno"]
                        )
                        meta[METADATA_FIELD] = "from_cost"
                        price_entry = data.Price(
                            meta,
                            entry.date,
                            units.currency,
                            amount.Amount(cost.number, cost.currency),
                        )
                else:
                    price_entry = None

                if price_entry is not None:
                    key = (
                        price_entry.date,
                        price_entry.currency,
                        price_entry.amount.number,  # Ideally should be removed.
                        price_entry.amount.currency,
                    )
                    if key not in new_price_entry_map:
                        new_price_entry_map[key] = price_entry
                        new_entries.append(price_entry)

    return new_entries, errors
