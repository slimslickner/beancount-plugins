"""Beancount plugins for transaction validation.

This package contains custom Beancount plugins designed for personal finance ledger
management. These plugins enhance Beancount's functionality with transaction validation
features.

INCLUDED PLUGINS:

1. check_missing_tags
   - Validates that transactions have required tags
   - Marks accounts as tag-required in their Open directives
   - Reports violations as parser errors for bean-check integration
   Usage: plugin "beancount_plugins.check_missing_tags"

2. check_valid_tags
   - Validates transaction tags against an allowed whitelist
   - Loads allowed tags from tags.yaml configuration
   - Reports violations for unknown tags
   - Prevents typos and enforces controlled vocabulary
   Usage: plugin "beancount_plugins.check_valid_tags"

3. check_valid_metadata
   - Validates metadata keys and values against a typed schema
   - Enforces type constraints (string, int, bool, date, Decimal)
   - Supports required fields and allowed_values constraints
   - Validates at transaction and posting levels
   - Reports violations with field context
   Usage: plugin "beancount_plugins.check_valid_metadata"

4. posting_tags
   - Enables per-posting tag granularity via 'tags' metadata on postings
   - Promotes posting-level tags to the transaction level for Fava/bean-query visibility
   - Preserves posting metadata for per-posting tag association
   - Reports errors for invalid tags metadata values
   Usage: plugin "beancount_plugins.posting_tags"

INTEGRATION:
Add plugins to your main ledger file as needed (order matters):

    plugin "beancount_plugins.posting_tags"
    plugin "beancount_plugins.check_missing_tags"
    plugin "beancount_plugins.check_valid_tags"
    plugin "beancount_plugins.check_valid_metadata"

Each plugin can be used independently based on your needs.

CONFIGURATION:
See individual plugin modules for detailed configuration options and examples:
- posting_tags: no config required
- check_valid_tags requires: tags.yaml
- check_valid_metadata requires: metadata_schema.yaml
"""
