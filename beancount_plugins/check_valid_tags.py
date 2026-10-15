#!/usr/bin/env python3
"""Beancount plugin to validate transaction tags against an allowed list.

This plugin enforces a controlled vocabulary for transaction tags by validating
that all tags used in transactions are defined in a configuration file. This
ensures consistent, predictable tagging practices and prevents typos.

WHAT IT DOES:
- Loads allowed tags from a YAML configuration file
- Validates all transaction tags against this whitelist
- Enforces link requirements for specific tags (require_link)
- Errors on declared-but-unused tags: any tag in the whitelist that never
  appears on a transaction is reported as stale/dead config
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
      pending:
        label: "Awaiting settlement"
        allow_unused: true  # Dormant between pay periods — don't flag when absent

REQUIRE_LINK:
When require_link is true for a tag, any transaction using that tag must also
have at least one link (^link-name). This is useful for tags like #reimbursable
where you want to ensure a reference to a reimbursement request or receipt.

UNUSED TAG CHECK:
Every tag declared in tags.yaml must be used by at least one transaction,
otherwise a ParserError is emitted at load time. "Used" means the tag appears
on a transaction. Posting-level tags promoted by the posting_tags plugin count
provided posting_tags runs before this plugin. This catches stale entries left
behind after a tag is retired.

Some tags are legitimately dormant for part of the year (e.g. #pending between
pay periods). Mark those with `allow_unused: true` on the tag definition to
exempt them from this check. The flag defaults to false, so every other tag is
still enforced. `allow_unused` is independent of `require_link`: a tag declared
with require_link is still reported as unused when no transaction uses it,
unless it also sets allow_unused.

NOTE: this check is unconditional. A tags.yaml loaded against a ledger with no
tagged transactions reports every declared tag without allow_unused as unused.

HOW IT WORKS:
1. Load the tags.yaml configuration file
2. Extract all allowed tag names and link requirements
3. For each transaction, validate that all tags are in the allowed set
4. For tags with require_link, validate that the transaction has links
5. Error on any declared tag that was never observed on a transaction
6. Report ParserErrors for any violations

ERROR REPORTING:
Errors are reported as ParserErrors with proper file/line information:

    your-file.bean:42: Undefined tag '#unknown-tag'
    your-file.bean:42: Tag '#reimbursable' requires a link (e.g., ^receipt-123)

Declared-but-unused tags are reported against the ledger file at line 0
(file-level, since there is no offending directive to point at):

    your-file.bean:0: check_valid_tags: Declared tag '#medical' is never used

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
    tags_allowing_unused: set[str] = set()
    tags_section = config_data.get("tags", {})
    if isinstance(tags_section, dict):
        allowed_tags = set(tags_section.keys())
        for tag_name, tag_spec in tags_section.items():
            if not isinstance(tag_spec, dict):
                continue
            if tag_spec.get("require_link") is True:
                tags_requiring_link.add(tag_name)
            if tag_spec.get("allow_unused") is True:
                tags_allowing_unused.add(tag_name)

    logger.debug("Loaded %d allowed tags: %s", len(allowed_tags), sorted(allowed_tags))
    if tags_requiring_link:
        logger.debug("Tags requiring links: %s", sorted(tags_requiring_link))
    if tags_allowing_unused:
        logger.debug("Tags allowed to be unused: %s", sorted(tags_allowing_unused))

    # Track which declared tags are actually used. Posting-level tags promoted
    # by the posting_tags plugin (loaded earlier) count too, since they appear
    # on the transaction by the time this plugin runs.
    used_tags: set[str] = set()

    # Validate transactions
    violations_count = 0

    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        if not entry.tags:
            continue

        used_tags.update(entry.tags)

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

    # Report declared-but-unused tags: any whitelist tag that never appeared on
    # a transaction is dead config, unless it opts out with allow_unused. Anchored
    # to the ledger file at line 0 (file-level) since an unused tag has no
    # offending directive to point at.
    unused_source = {
        "filename": options_map.get("filename", "unknown"),
        "lineno": 0,
    }
    for tag in sorted(allowed_tags - used_tags - tags_allowing_unused):
        violations_count += 1
        errors.append(
            ParserError(
                source=dict(unused_source),
                message=f"check_valid_tags: Declared tag '#{tag}' is never used",
                entry=None,
            )
        )

    # Log summary
    if violations_count > 0:
        logger.warning("Found %d tag validation errors", violations_count)
    else:
        logger.debug("All transaction tags are valid")

    return entries, errors
