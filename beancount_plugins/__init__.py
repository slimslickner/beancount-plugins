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

INTEGRATION:
Add these plugins to your main ledger file:

    plugin "beancount_plugins.zerosum_transaction_matcher"
    plugin "beancount_plugins.check_missing_tags"

Each plugin can be used independently based on your needs.

CONFIGURATION:
See individual plugin modules for detailed configuration options and examples.
"""
