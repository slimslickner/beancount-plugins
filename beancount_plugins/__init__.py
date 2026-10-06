"""Beancount plugins for transfer matching and validation.

This package contains custom Beancount plugins designed for personal finance ledger
management. These plugins enhance Beancount's functionality with transfer matching
and transaction validation features.

INCLUDED PLUGINS:

1. zerosum_transaction_matcher
   - Matches transfer postings between accounts
   - Automatically detects counterparties for Equity:ZeroSum entries
   - Adds enriched metadata for transfer reconciliation
   - Works with Beancount's built-in zerosum plugin
   Usage: plugin "beancount_plugins.zerosum_transaction_matcher"

2. check_missing_tags
   - Validates that transactions have required tags
   - Marks accounts as tag-required in their Open directives
   - Reports violations as parser errors for bean-check integration
   Usage: plugin "beancount_plugins.check_missing_tags"

3. check_missing_links
   - Validates that transactions have required links
   - Marks accounts as link-required via 'link-expected: True' in Open directives
   - Useful for accounts receivable, reimbursable expenses, and other traceable accounts
   - Reports violations as parser errors for bean-check integration
   Usage: plugin "beancount_plugins.check_missing_links"

4. check_valid_tags
   - Validates transaction tags against an allowed whitelist
   - Loads allowed tags from tags.yaml configuration
   - Reports violations for unknown tags
   - Prevents typos and enforces controlled vocabulary
   Usage: plugin "beancount_plugins.check_valid_tags"

5. check_valid_metadata
   - Validates metadata keys and values against a typed schema
   - Enforces type constraints (string, int, bool, date, Decimal)
   - Supports required fields and allowed_values constraints
   - Validates at transaction and posting levels
   - Reports violations with field context
   Usage: plugin "beancount_plugins.check_valid_metadata"

6. posting_tags
   - Enables per-posting tag granularity via 'tags' metadata on postings
   - Promotes posting-level tags to the transaction level for Fava/bean-query visibility
   - Preserves posting metadata for per-posting tag association
   - Reports errors for invalid tags metadata values
   Usage: plugin "beancount_plugins.posting_tags"

7. transfer_remove_payee
   - Errors on transactions that look like transfers (between Assets/Liabilities/Equity
     accounts) but have a payee set — almost always a mistake
   - Emits a ParserError per violation; the ledger fails to load until fixed
   - Excludes Assets:Receivable:* (AR legitimately uses payees for invoices)
   - Skips transfers where all postings share the same immediate parent
     (e.g. Assets:Checking <-> Assets:Savings — narration is enough)
   Usage: plugin "beancount_plugins.transfer_remove_payee"

8. missing_contribution_year
   - Errors on retirement contributions that lack a `contribution-year` key on
     the RECEIVING posting (the destination) — needed for grouping
     contributions by tax year
   - Emits a ParserError per violation; the ledger fails to load until fixed
   - The contribution-year metadata must be on the destination posting, NOT
     on the transaction — this allows per-destination year tracking in
     multi-account transactions.
   - Requires a "counterparty" posting (employer contribution, transfer from
     checking, ZeroSum-matched transfer) to qualify — random asset movements
     don't count
   - PRIMARY mode is exact account match (destination_accounts) — no regex
     foot-guns, O(1) lookups. Regex patterns (destination_patterns) are a
     fallback for convention-based matching. When destination_accounts is
     set (non-empty), default patterns are replaced.
   - Load-time validation: explicitly-configured accounts must have an Open
     directive (or an ancestor component must). Typos in config produce
     ParserErrors instead of silently failing to flag transactions.
   Usage: plugin "beancount_plugins.missing_contribution_year"
   Usage: plugin "beancount_plugins.missing_contribution_year" "{
       'destination_accounts': ['Assets:Retirement:401k:Cash'],
       'counterparty_accounts': ['Income:ACME:Employer-Contribution']
   }"

9. promote_account_metadata
   - Copies metadata from each account's Open directive onto postings for
     that account, so account-level annotations (e.g. tax-treatment,
     cost-center, department) flow down to individual postings for queries
     and downstream plugins
   - Existing posting values win on conflict; a WARNING is logged for each
     conflict (visible with `bean-check -v`)
   - System keys (filename, lineno) are never promoted
   - Optional inline dict config: `whitelist` (only promote these keys),
     `blacklist` (promote all except these). Whitelist wins if both provided.
   Usage: plugin "beancount_plugins.promote_account_metadata"
   Usage: plugin "beancount_plugins.promote_account_metadata" "{
       'whitelist': ['tax-treatment']
   }"

10. implicit_prices_flagged
   - Drop-in replacement for `beancount.plugins.implicit_prices` that honors
     a per-posting `no-implicit-price: TRUE` opt-out for cost-derived prices
     (e.g. in-kind transfers whose cost basis is not today's market price
     and shouldn't be recorded as one)
   - Injects synthesized `Price` entries tagged with `__implicit_prices__:
     from_price` or `from_cost`
   - USE INSTEAD OF, not alongside, `beancount.plugins.implicit_prices` —
     running both will just re-add the prices this one skips
   Usage: plugin "beancount_plugins.implicit_prices_flagged"

11. block_transactions
   - Blocks transactions on accounts marked `block-transactions: TRUE` in
     their Open directive — useful for parent accounts opened only to attach
     Fava documents (e.g. `Assets:Investment:Brokerage`)
   - Matching is exact, so sub-accounts (e.g.
     `Assets:Investment:Brokerage:USD`) remain usable
   - Default is off; only accounts that opt in are enforced
   - Reports violations as parser errors for bean-check integration
   Usage: plugin "beancount_plugins.block_transactions"

INTEGRATION:
Add plugins to your main ledger file as needed (order matters):

    plugin "beancount_plugins.posting_tags"
    plugin "beancount_plugins.implicit_prices_flagged"
    plugin "beancount_plugins.transfer_remove_payee"
    plugin "beancount_plugins.block_transactions"
    plugin "beancount_plugins.missing_contribution_year"
    plugin "beancount_plugins.zerosum_transaction_matcher"
    plugin "beancount_plugins.check_missing_tags"
    plugin "beancount_plugins.check_missing_links"
    plugin "beancount_plugins.check_valid_tags"
    plugin "beancount_plugins.promote_account_metadata"
    plugin "beancount_plugins.check_valid_metadata"

Each plugin can be used independently based on your needs.

CONFIGURATION:
See individual plugin modules for detailed configuration options and examples:
- posting_tags: no config required
- transfer_remove_payee: no config required; if combined with check_valid_tags,
  add 'transfer-remove-payee' to tags.yaml
- block_transactions: no config; opt in per account with
  `block-transactions: TRUE` on its Open directive
- missing_contribution_year: inline dict overrides destination_accounts,
  destination_patterns, and/or counterparty_accounts. Explicit destination_accounts
  replaces default patterns (no silent regex fallback). Explicitly-configured
  accounts are validated against Open directives.
- promote_account_metadata: inline dict with `whitelist` (string or list of
  keys to promote) or `blacklist` (string or list of keys to exclude).
  Whitelist wins if both provided. System keys (filename, lineno) are
  never promoted.
- implicit_prices_flagged: no config; opt out per-posting with
  `no-implicit-price: TRUE` metadata on the posting you want to skip
- check_valid_tags requires: tags.yaml
- check_valid_metadata requires: metadata_schema.yaml
"""
