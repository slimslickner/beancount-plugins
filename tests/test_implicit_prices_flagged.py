"""Unit tests for implicit_prices_flagged plugin."""

from beancount import loader
from beancount.core import data

# ---------------------------------------------------------------------------
# Ledgers
# ---------------------------------------------------------------------------

_FLAGGED_BUY_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Equity:Opening-Balances

2025-02-01 * "Buy GOOG"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD}
    no-implicit-price: TRUE
  Equity:Opening-Balances
"""

_TRANSFER_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Assets:Brokerage:NewFirm:GOOG
2025-02-01 open Equity:Opening-Balances

2025-02-01 * "Buy GOOG"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD}
    no-implicit-price: TRUE
  Equity:Opening-Balances

2026-07-13 * "In-kind transfer of GOOG to new brokerage"
  Assets:Brokerage:OldFirm:GOOG    -1 GOOG {170.00 USD, 2025-02-01}
  Assets:Brokerage:NewFirm:GOOG     1 GOOG {170.00 USD, 2025-02-01}
    no-implicit-price: TRUE
"""

_UNFLAGGED_BUY_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Equity:Opening-Balances

2025-02-01 * "Buy GOOG"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD}
  Equity:Opening-Balances
"""

_REDUCING_SELL_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Equity:Opening-Balances
2025-02-01 open Income:Gains

2025-02-01 * "Buy GOOG"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD}
    no-implicit-price: TRUE
  Equity:Opening-Balances

2026-07-13 * "Sell 1 GOOG"
  Assets:Brokerage:OldFirm:GOOG   -1 GOOG {170.00 USD, 2025-02-01} @ 320.00 USD
  Income:Gains
"""

_EXPLICIT_PRICE_FLAGGED_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Equity:Opening-Balances

2025-02-01 * "Buy GOOG with explicit price, flagged"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD} @ 170.00 USD
    no-implicit-price: TRUE
  Equity:Opening-Balances
"""

_FULL_TRANSFER_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Assets:Brokerage:NewFirm:GOOG
2025-02-01 open Equity:Opening-Balances

2025-02-01 * "Buy 2 GOOG"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD}
    no-implicit-price: TRUE
  Equity:Opening-Balances

2026-07-13 * "In-kind transfer of 1 GOOG to new brokerage"
  Assets:Brokerage:OldFirm:GOOG    -1 GOOG {170.00 USD, 2025-02-01}
  Assets:Brokerage:NewFirm:GOOG     1 GOOG {170.00 USD, 2025-02-01}
    no-implicit-price: TRUE

2026-08-01 * "Buy more GOOG at NewFirm, real trade"
  Assets:Brokerage:NewFirm:GOOG   1 GOOG {320.00 USD}
  Equity:Opening-Balances
"""

_NO_METADATA_LEDGER = """\
option "operating_currency" "USD"
plugin "beancount_plugins.implicit_prices_flagged"

2025-02-01 open Assets:Brokerage:OldFirm:GOOG
2025-02-01 open Equity:Opening-Balances

2025-02-01 * "Buy GOOG, no metadata at all"
  Assets:Brokerage:OldFirm:GOOG   2 GOOG {170.00 USD}
  Equity:Opening-Balances
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_prices(entries):
    """Return all Price directives from a list of entries, as
    (date, currency, number, cost_currency) tuples for easy comparison."""
    return [
        (e.date, e.currency, e.amount.number, e.amount.currency)
        for e in entries
        if isinstance(e, data.Price)
    ]


# ---------------------------------------------------------------------------
# Flagged postings skip cost-derived prices
# ---------------------------------------------------------------------------


class TestFlaggedPostingSkipsPrice:
    def test_flagged_buy_skips_implicit_price(self):
        """A posting with no-implicit-price: TRUE should NOT generate
        an implicit price, even though it has a cost."""
        entries, errors, _ = loader.load_string(_FLAGGED_BUY_LEDGER)
        assert not errors
        prices = _get_prices(entries)
        assert prices == []

    def test_transfer_with_flagged_incoming_skips_price(self):
        """In-kind transfer where the incoming posting is flagged should
        not synthesize a price on the transfer date."""
        entries, errors, _ = loader.load_string(_TRANSFER_LEDGER)
        assert not errors
        prices = _get_prices(entries)
        assert prices == []


# ---------------------------------------------------------------------------
# Unflagged cost postings still generate implicit prices
# ---------------------------------------------------------------------------


class TestUnflaggedCostPosting:
    def test_normal_purchase_still_generates_price(self):
        """A normal purchase without the flag should still generate an
        implicit price, same as the stock plugin would."""
        import datetime

        entries, errors, _ = loader.load_string(_UNFLAGGED_BUY_LEDGER)
        assert not errors
        prices = _get_prices(entries)
        assert prices == [(datetime.date(2025, 2, 1), "GOOG", 170.00, "USD")]


# ---------------------------------------------------------------------------
# Reducing legs and explicit prices
# ---------------------------------------------------------------------------


class TestReducingLeg:
    def test_reducing_sale_never_synthesizes_price(self):
        """Reducing an existing lot should never synthesize a price,
        regardless of the flag (matches stock implicit_prices behavior)."""
        import datetime

        entries, errors, _ = loader.load_string(_REDUCING_SELL_LEDGER)
        assert not errors
        prices = _get_prices(entries)
        # The sale has an explicit @ price -- that SHOULD still generate
        # a price entry, dated on the sale date, not the original purchase date.
        assert prices == [(datetime.date(2026, 7, 13), "GOOG", 320.00, "USD")]


class TestExplicitPriceAnnotation:
    def test_explicit_price_annotation_ignores_flag(self):
        """An explicit @ price annotation should generate a price entry
        even if the posting is flagged -- the flag only suppresses
        cost-derived prices, not explicit ones."""
        import datetime

        entries, errors, _ = loader.load_string(_EXPLICIT_PRICE_FLAGGED_LEDGER)
        assert not errors
        prices = _get_prices(entries)
        assert prices == [(datetime.date(2025, 2, 1), "GOOG", 170.00, "USD")]


# ---------------------------------------------------------------------------
# End-to-end scenario
# ---------------------------------------------------------------------------


class TestFullTransferScenario:
    def test_transfer_date_has_no_synthesized_price(self):
        """End-to-end: the exact transfer scenario -- confirm no GOOG price
        shows up on the transfer date, but the real trade still does."""
        import datetime

        entries, errors, _ = loader.load_string(_FULL_TRANSFER_LEDGER)
        assert not errors
        prices = _get_prices(entries)
        dates = [p[0] for p in prices]
        assert datetime.date(2026, 7, 13) not in dates
        assert (datetime.date(2026, 8, 1), "GOOG", 320.00, "USD") in prices
        # Only the real trade should have produced a price.
        assert len(prices) == 1


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestMissingMetadata:
    def test_posting_with_no_metadata_does_not_crash(self):
        """Postings with no metadata at all (posting.meta could be None
        or empty dict) should not raise an AttributeError."""
        entries, errors, _ = loader.load_string(_NO_METADATA_LEDGER)
        assert not errors
        # Should still produce the implicit price.
        prices = _get_prices(entries)
        assert len(prices) == 1
