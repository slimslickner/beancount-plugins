# Beancount Plugins

Personal helper plugins for the Beancount finance ledger. These plugins are designed to work with a specific Beancount configuration and may not be suitable for general use without modification.

## Plugins

1. **zerosum_transaction_matcher** - Identifies and matches transfer postings between accounts, adding metadata for transfer reconciliation
2. **check_missing_tags** - Validates that transactions posting to tag-required accounts include tags
3. **check_missing_links** - Validates that transactions posting to link-required accounts include a link
4. **check_valid_tags** - Validates transaction tags against an allowed whitelist (requires `tags.yaml`)
5. **check_valid_metadata** - Validates metadata keys and values against a typed schema (requires `metadata_schema.yaml`)
6. **posting_tags** - Enables per-posting tags via `tags` metadata, promoting them to the transaction level for Fava/bean-query visibility
7. **transfer_remove_payee** - Errors on transactions that look like transfers (Assets/Liabilities/Equity only) but incorrectly carry a payee
8. **missing_contribution_year** - Errors on retirement contributions missing a `contribution-year` metadata key on the **receiving posting** (the destination, not the transaction itself); primary mode is exact-match on `destination_accounts` (validated against Open directives at load time), with regex `destination_patterns` as a fallback. Counterparty accounts are configurable via inline dict.

## Usage

These plugins are installed as a local package dependency and can be used in Beancount configuration files via:

```beancount
plugin "beancount_plugins.posting_tags"
plugin "beancount_plugins.transfer_remove_payee"
plugin "beancount_plugins.missing_contribution_year"
plugin "beancount_plugins.zerosum_transaction_matcher"
plugin "beancount_plugins.check_missing_tags"
plugin "beancount_plugins.check_missing_links"
plugin "beancount_plugins.check_valid_tags"
plugin "beancount_plugins.check_valid_metadata"
```

Each plugin can be used independently based on your needs. See individual plugin modules for detailed documentation and configuration options.

## Configuration: `missing_contribution_year`

Three optional inline-dict keys; both lists can be specified together (union):

```beancount
plugin "beancount_plugins.missing_contribution_year" "{
    'destination_accounts': [
        'Assets:Retirement:401k:Fidelity-401k:Cash',
        'Assets:Retirement:HSA:Fidelity-HSA:Cash'
    ],
    'counterparty_accounts': [
        'Equity:ZeroSumMatched:Transfers',
        'Income:CapTech:Employer-Contribution'
    ]
}"
```

- `destination_accounts` (PRIMARY): exact account names, O(1) lookups, no regex foot-guns. When set (non-empty), default `destination_patterns` are replaced.
- `destination_patterns` (fallback): regex substring matching for convention-based detection.
- `counterparty_accounts`: exact account names of known contribution sources (employer contributions, transfers from checking).

Any account explicitly listed in `destination_accounts` or `counterparty_accounts` is checked against Open directives at load time. Typos produce ParserErrors instead of silently no-op'ing.

The `contribution-year` key lives on the **destination posting** (not on the transaction), so transactions that contribute to multiple retirement accounts in one entry can carry separate years per posting:

```beancount
2026-07-31 * "Employee Contribution"
    Assets:Investment:HSA:Tims-HealthEquity:Cash       139.23 USD
        contribution-year: "2026"
    Equity:ZeroSum:Transfers
```
