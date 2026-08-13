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
   - Flags transactions that look like transfers (between Assets/Liabilities/Equity
     accounts) but have a payee set — almost always a mistake
   - Tags matched transactions with #transfer-remove-payee and sets the flag to '!'
   - Excludes Assets:Receivable:* (AR legitimately uses payees for invoices)
   - Skips transfers where all postings share the same immediate parent
     (e.g. Assets:Checking <-> Assets:Savings — narration is enough)
   Usage: plugin "beancount_plugins.transfer_remove_payee"

8. missing_contribution_year
   - Flags retirement contributions that lack a `contribution-year` key on
     the RECEIVING posting (the destination) — needed for grouping
     contributions by tax year
   - Tags matched transactions with #missing-contribution-year and sets flag to '!'
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
       'counterparty_accounts': ['Income:CapTech:Employer-Contribution']
   }"

INTEGRATION:
Add plugins to your main ledger file as needed (order matters):

    plugin "beancount_plugins.posting_tags"
    plugin "beancount_plugins.transfer_remove_payee"
    plugin "beancount_plugins.missing_contribution_year"
    plugin "beancount_plugins.zerosum_transaction_matcher"
    plugin "beancount_plugins.check_missing_tags"
    plugin "beancount_plugins.check_missing_links"
    plugin "beancount_plugins.check_valid_tags"
    plugin "beancount_plugins.check_valid_metadata"

Each plugin can be used independently based on your needs.

CONFIGURATION:
See individual plugin modules for detailed configuration options and examples:
- posting_tags: no config required
- transfer_remove_payee: no config required; if combined with check_valid_tags,
  add 'transfer-remove-payee' to tags.yaml
- missing_contribution_year: inline dict overrides destination_accounts,
  destination_patterns, and/or counterparty_accounts. Explicit destination_accounts
  replaces default patterns (no silent regex fallback). Explicitly-configured
  accounts are validated against Open directives.
- check_valid_tags requires: tags.yaml
- check_valid_metadata requires: metadata_schema.yaml
"""
