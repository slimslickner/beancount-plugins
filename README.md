# Beancount Plugins

Personal helper plugins for the Beancount finance ledger. These plugins are designed to work with a specific Beancount configuration and may not be suitable for general use without modification.

## Plugins

- **zerosum_transaction_matcher** - Identifies and matches transfer postings between accounts, adding metadata for transfer reconciliation
- **check_missing_tags** - Validates that transactions have required tags and reports missing tag violations

## Usage

These plugins are installed as a local package dependency and can be used in Beancount configuration files via:

```beancount
plugin "beancount_plugins.zerosum_transaction_matcher"
plugin "beancount_plugins.check_missing_tags"
```
