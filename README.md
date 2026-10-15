# Beancount Plugins

Personal helper plugins for the Beancount finance ledger. These plugins are designed to work with a specific Beancount configuration and may not be suitable for general use without modification.

## Plugins

1. **zerosum_transaction_matcher** - Identifies and matches transfer postings between accounts, adding metadata for transfer reconciliation
2. **check_missing_tags** - Validates that transactions posting to tag-required accounts include tags
3. **check_missing_links** - Validates that transactions posting to link-required accounts include a link
4. **check_valid_tags** - Validates transaction tags against an allowed whitelist (requires `tags.yaml`)
5. **check_valid_metadata** - Validates metadata keys and values against a typed schema, with optional `account_pattern` scoping (fields only allowed on matching accounts; required there when required). Requires `metadata_schema.yaml`
6. **posting_tags** - Enables per-posting tags via `tags` metadata, promoting them to the transaction level for Fava/bean-query visibility
7. **transfer_remove_payee** - Errors on transactions that look like transfers (Assets/Liabilities/Equity only) but incorrectly carry a payee
8. **missing_contribution_year** - Errors on retirement contributions missing a `contribution-year` metadata key on the **receiving posting** (the destination, not the transaction itself); primary mode is exact-match on `destination_accounts` (validated against Open directives at load time), with regex `destination_patterns` as a fallback. Counterparty accounts are configurable via inline dict.
9. **promote_account_metadata** - Copies metadata from each account's Open directive onto postings for that account, so account-level annotations flow down to individual postings. Optional `whitelist`/`blacklist` inline-dict config.
10. **implicit_prices_flagged** - Drop-in replacement for Beancount's built-in `implicit_prices` that honors a per-posting `no-implicit-price: TRUE` opt-out for cost-derived prices. Use instead of, not alongside, the built-in.
11. **block_transactions** - Errors on any posting to an account whose Open directive sets `block-transactions: TRUE`. Matching is exact, so sub-accounts remain usable. Useful for parent accounts opened only to attach Fava documents (e.g. `Assets:Investment:Brokerage`).
12. **aggregate_account_metadata** - Derives aggregated metadata keys on Open directives from a source key (e.g. `account-type` → `asset-class`) via a value mapping. Supports multiple aggregations in one `aggregations` inline-dict config; load before `promote_account_metadata`.

## Usage

These plugins are installed as a local package dependency and can be used in Beancount configuration files via:

```beancount
plugin "beancount_plugins.posting_tags"
plugin "beancount_plugins.implicit_prices_flagged"
plugin "beancount_plugins.transfer_remove_payee"
plugin "beancount_plugins.block_transactions"
plugin "beancount_plugins.missing_contribution_year"
plugin "beancount_plugins.zerosum_transaction_matcher"
plugin "beancount_plugins.check_missing_tags"
plugin "beancount_plugins.check_missing_links"
plugin "beancount_plugins.check_valid_tags"
plugin "beancount_plugins.aggregate_account_metadata"
plugin "beancount_plugins.promote_account_metadata"
plugin "beancount_plugins.check_valid_metadata"
```

Each plugin can be used independently based on your needs. See individual plugin modules for detailed documentation and configuration options.
