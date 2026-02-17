# Beancount Plugins

Personal helper plugins for the Beancount finance ledger. These plugins are designed to work with a specific Beancount configuration and may not be suitable for general use without modification.

## Plugins

1. **zerosum_transaction_matcher** - Identifies and matches transfer postings between accounts, adding metadata for transfer reconciliation
2. **check_missing_tags** - Validates that transactions posting to tag-required accounts include tags
3. **check_valid_tags** - Validates transaction tags against an allowed whitelist (requires `tags.yaml`)
4. **check_valid_metadata** - Validates metadata keys and values against a typed schema (requires `metadata_schema.yaml`)

## Usage

These plugins are installed as a local package dependency and can be used in Beancount configuration files via:

```beancount
plugin "beancount_plugins.zerosum_transaction_matcher"
plugin "beancount_plugins.check_missing_tags"
plugin "beancount_plugins.check_valid_tags"
plugin "beancount_plugins.check_valid_metadata"
```

Each plugin can be used independently based on your needs. See individual plugin modules for detailed documentation and configuration options.
