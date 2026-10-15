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

Optional config. The second argument is dual-mode: it may be a path to a
tags.yaml file, OR an inline Python dict literal mirroring the file's shape.
The mode is chosen by a simple rule — if the argument (after stripping
whitespace) starts with '{', it is parsed as an inline dict; otherwise it is
treated as a file path.

Alternate config file:
    plugin "beancount_plugins.check_valid_tags" "/path/to/tags.yaml"

Inline config (Python dict literal, top-level 'tags' key required):
    plugin "beancount_plugins.check_valid_tags" "{
        'tags': {
            'travel': {'label': 'Travel'},
            'reimbursable': {'label': 'Be reimbursed', 'require_link': True}
        }
    }"

The inline dict uses Python literal syntax (parsed via ast.literal_eval):
single or double quotes, and booleans as True/False — not YAML/JSON's
true/false.

DEFAULT:
When no config is given, tags.yaml is loaded from the ledger file's directory.

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

import ast
import logging
from pathlib import Path
from typing import Any

import yaml
from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_valid_tags",)

# ParserError source used for config-level problems (no offending directive).
_CONFIG_SOURCE: dict[str, Any] = {"filename": "plugin config", "lineno": 0}


def _load_config(
    config: str | None,
    ledger_dir: Path,
) -> tuple[dict[str, Any], list[ParserError]]:
    """Load tags configuration from either an inline dict or a YAML file path.

    The second plugin argument is dual-mode: if it starts with '{' it is parsed
    as an inline Python dict literal; otherwise it is treated as a path to a
    tags.yaml file (resolved relative to the ledger directory when relative).
    When no config is supplied, tags.yaml is loaded from the ledger directory.

    Returns (config_data, errors). On error config_data is an empty dict and the
    caller should return the entries unchanged.
    """
    errors: list[ParserError] = []

    if config and config.strip().startswith("{"):
        try:
            parsed: Any = ast.literal_eval(config)
        except (ValueError, SyntaxError) as e:
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        f"check_valid_tags: Invalid inline config: {e}. "
                        "Use Python literal syntax (single or double quotes, "
                        "True/False — not YAML/JSON true/false)."
                    ),
                    entry=None,
                )
            )
            return {}, errors

        if not isinstance(parsed, dict):
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        "check_valid_tags: config must be a dict, "
                        f"got {type(parsed).__name__}"
                    ),
                    entry=None,
                )
            )
            return {}, errors

        tags_section = parsed.get("tags")
        if tags_section is not None and not isinstance(tags_section, dict):
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        "check_valid_tags: 'tags' must be a dict mapping tag "
                        f"names to specs, got {type(tags_section).__name__}"
                    ),
                    entry=None,
                )
            )
            return {}, errors

        return parsed, errors

    # Not an inline dict. Guard against config strings that plainly cannot be
    # file paths: a stray literal (e.g. a YAML block pasted inline, or an inline
    # dict whose leading '{' was lost) would otherwise be handed to the
    # filesystem, where Path.exists()/open() raise OSError(ENAMETOOLONG) on some
    # platforms and abort the whole plugin with an opaque traceback. Only the
    # component check matches the OS limit, so long-but-valid absolute paths
    # still work.
    if config:
        _parts = config.replace("\\", "/").split("/")
        if "\n" in config or any(len(part) > 255 for part in _parts):
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        "check_valid_tags: config is neither a valid inline dict "
                        "literal nor a usable file path (it contains newlines or "
                        "a path component over 255 characters). Use an inline "
                        "Python dict literal starting with '{', or a path to "
                        "tags.yaml."
                    ),
                    entry=None,
                )
            )
            return {}, errors

    # File-path mode (default or explicit).
    if config:
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = ledger_dir / config_path
    else:
        config_path = ledger_dir / "tags.yaml"

    try:
        if not config_path.exists():
            errors.append(
                ParserError(
                    source={"filename": "tags.yaml", "lineno": 0},
                    message=f"Tags configuration file not found: {config_path}",
                    entry=None,
                )
            )
            logger.warning("Tags configuration file not found: %s", config_path)
            return {}, errors

        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        errors.append(
            ParserError(
                source={"filename": str(config_path), "lineno": 0},
                message=f"Failed to load tags configuration: {e}",
                entry=None,
            )
        )
        logger.error("Failed to load tags configuration: %s", e)
        return {}, errors

    return config_data, errors


def check_valid_tags(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> tuple[data.Entries, list[ParserError]]:
    """Validate that all transaction tags are in the allowed list.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional dual-mode config — an inline Python dict literal (must
            start with '{' and carry a top-level 'tags' key) or a path to a
            tags.yaml file. Defaults to tags.yaml in the ledger directory.

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors: list[ParserError] = []

    # Load configuration: inline dict literal or tags.yaml file path.
    ledger_dir = Path(options_map.get("filename", "")).parent
    config_data, config_errors = _load_config(config, ledger_dir)
    if config_errors:
        return entries, config_errors

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
