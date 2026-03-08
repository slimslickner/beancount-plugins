#!/usr/bin/env python3
"""Beancount plugin to validate transaction tags against an allowed list.

This plugin enforces a controlled vocabulary for transaction tags by validating
that all tags used in transactions are defined in a configuration file. This
ensures consistent, predictable tagging practices and prevents typos.

WHAT IT DOES:
- Loads allowed tags from a YAML configuration file
- Validates all transaction tags against this whitelist
- Enforces link requirements for specific tags (require_link)
- Reports violations as parser errors with proper file/line references
- Integrates seamlessly with bean-check for validation pipelines

USAGE:
In your main ledger file:
    plugin "beancount_plugins.check_valid_tags"

Optional config (specify alternate config file):
    plugin "beancount_plugins.check_valid_tags" "/path/to/tags.yaml"

CONFIG FILE FORMAT:
Create a tags.yaml file in your ledger directory with:

    tags:
      tax-deductible:
        label: "Expenses that may be tax-deductible"
      reimbursable:
        label: "Expenses to be reimbursed"
        require_link: true  # Transactions with this tag must have a link
      travel:
        label: "Travel-related expenses"
      medical:
        label: "Medical expenses"

REQUIRE_LINK:
When require_link is true for a tag, any transaction using that tag must also
have at least one link (^link-name). This is useful for tags like #reimbursable
where you want to ensure a reference to a reimbursement request or receipt.

HOW IT WORKS:
1. Load the tags.yaml configuration file
2. Extract all allowed tag names and link requirements
3. For each transaction, validate that all tags are in the allowed set
4. For tags with require_link, validate that the transaction has links
5. Report ParserErrors for any violations

ERROR REPORTING:
Errors are reported as ParserErrors with proper file/line information:

    your-file.bean:42: Undefined tag '#unknown-tag'
    your-file.bean:42: Tag '#reimbursable' requires a link (e.g., ^receipt-123)

COMPLEMENTARY PLUGINS:
- check_missing_tags: Enforces that certain accounts have tags
- check_valid_metadata: Validates metadata keys and values
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from pathlib import Path

import yaml
from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_valid_tags",)


def check_valid_tags(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> tuple[data.Entries, list[ParserError]]:
    """Validate that all transaction tags are in the allowed list.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config path (defaults to tags.yaml in ledger directory)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors: list[ParserError] = []

    # Determine config file path, resolved relative to the ledger file's directory.
    ledger_dir = Path(options_map.get("filename", "")).parent
    if config:
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = ledger_dir / config_path
    else:
        config_path = ledger_dir / "tags.yaml"

    # Load configuration
    if not config_path.exists():
        error = ParserError(
            source={"filename": "tags.yaml", "lineno": 0},
            message=f"Tags configuration file not found: {config_path}",
            entry=None,
        )
        errors.append(error)
        logger.warning("Tags configuration file not found: %s", config_path)
        return entries, errors

    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        error = ParserError(
            source={"filename": str(config_path), "lineno": 0},
            message=f"Failed to load tags configuration: {e}",
            entry=None,
        )
        errors.append(error)
        logger.error("Failed to load tags configuration: %s", e)
        return entries, errors

    # Extract allowed tags and link requirements
    allowed_tags: set[str] = set()
    tags_requiring_link: set[str] = set()
    tags_section = config_data.get("tags", {})
    if isinstance(tags_section, dict):
        allowed_tags = set(tags_section.keys())
        for tag_name, tag_spec in tags_section.items():
            if isinstance(tag_spec, dict) and tag_spec.get("require_link") is True:
                tags_requiring_link.add(tag_name)

    logger.debug("Loaded %d allowed tags: %s", len(allowed_tags), sorted(allowed_tags))
    if tags_requiring_link:
        logger.debug("Tags requiring links: %s", sorted(tags_requiring_link))

    # Validate transactions
    violations_count = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        if not entry.tags:
            continue

        source = {
            "filename": entry.meta.get("filename", "unknown"),
            "lineno": entry.meta.get("lineno", 0),
        }

        # Validate each tag
        for tag in entry.tags:
            if tag not in allowed_tags:
                violations_count += 1
                error = ParserError(
                    source=source,
                    message=f"Undefined tag '#{tag}'",
                    entry=None,
                )
                errors.append(error)
                continue

            # Check link requirement
            if tag in tags_requiring_link and not entry.links:
                violations_count += 1
                error = ParserError(
                    source=source,
                    message=f"Tag '#{tag}' requires a link (e.g., ^receipt-123)",
                    entry=None,
                )
                errors.append(error)

    # Log summary
    if violations_count > 0:
        logger.warning("Found %d tag validation errors", violations_count)
    else:
        logger.debug("All transaction tags are valid")

    return entries, errors
