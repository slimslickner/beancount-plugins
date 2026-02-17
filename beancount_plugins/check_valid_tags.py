#!/usr/bin/env python3
"""Beancount plugin to validate transaction tags against an allowed list.

This plugin enforces a controlled vocabulary for transaction tags by validating
that all tags used in transactions are defined in a configuration file. This
ensures consistent, predictable tagging practices and prevents typos.

WHAT IT DOES:
- Loads allowed tags from a YAML configuration file
- Validates all transaction tags against this whitelist
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
        description: "Expenses that may be tax-deductible"
      reimbursable:
        description: "Expenses to be reimbursed"
      travel:
        description: "Travel-related expenses"
      medical:
        description: "Medical expenses"

HOW IT WORKS:
1. Load the tags.yaml configuration file
2. Extract all allowed tag names
3. For each transaction, validate that all tags are in the allowed set
4. Report ParserErrors for any unrecognized tags

ERROR REPORTING:
Errors are reported as ParserErrors with proper file/line information:

    your-file.bean:42: Invalid tag '#unknown-tag' (allowed: tax-deductible, reimbursable, travel, medical)

COMPLEMENTARY PLUGINS:
- check_missing_tags: Enforces that certain accounts have tags
- check_valid_metadata: Validates metadata keys and values
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
from pathlib import Path
from typing import List, Tuple

import yaml
from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_valid_tags",)


def check_valid_tags(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Validate that all transaction tags are in the allowed list.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config path (defaults to tags.yaml in ledger directory)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors = []

    # Determine config file path
    if config:
        config_path = Path(config)
    else:
        # Default to tags.yaml in the same directory as main.bean
        # The ledger directory is typically available via options_map
        ledger_dir = Path.cwd()
        config_path = ledger_dir / "tags.yaml"

    # Load configuration
    if not config_path.exists():
        error = ParserError(
            source={"filename": "tags.yaml", "lineno": 0},
            message=f"Tags configuration file not found: {config_path}",
            entry=None,
        )
        errors.append(error)
        logger.warning(f"Tags configuration file not found: {config_path}")
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
        logger.error(f"Failed to load tags configuration: {e}")
        return entries, errors

    # Extract allowed tags
    allowed_tags = set()
    tags_section = config_data.get("tags", {})
    if isinstance(tags_section, dict):
        allowed_tags = set(tags_section.keys())

    logger.info(f"Loaded {len(allowed_tags)} allowed tags: {sorted(allowed_tags)}")

    # Validate transactions
    violations_count = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Check if transaction has tags
        if not entry.tags:
            continue

        # Validate each tag
        for tag in entry.tags:
            if tag not in allowed_tags:
                violations_count += 1
                error = ParserError(
                    source={
                        "filename": entry.meta.get("filename", "unknown"),
                        "lineno": entry.meta.get("lineno", 0),
                    },
                    message=(f"Undefined tag '#{tag}'"),
                    entry=None,
                )
                errors.append(error)

    # Log summary
    if violations_count > 0:
        logger.warning(f"Found {violations_count} invalid tags")
    else:
        logger.info("All transaction tags are valid")

    return entries, errors
