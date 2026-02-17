#!/usr/bin/env python3
"""Beancount plugin to validate metadata keys and values against a schema.

This plugin enforces a typed metadata schema across transactions and postings,
ensuring data quality and consistency. It validates metadata key names,
required vs. optional fields, and enforces type constraints and allowed values.

WHAT IT DOES:
- Loads metadata schema from a YAML configuration file
- Validates transaction-level metadata keys and values
- Validates posting-level metadata keys and values
- Enforces type constraints (string, int, bool, date, Decimal)
- Enforces allowed_values constraints
- Enforces pattern constraints (regex for strings)
- Reports violations as parser errors with field context

USAGE:
In your main ledger file:
    plugin "beancount_plugins.check_valid_metadata"

Optional config (specify alternate schema file):
    plugin "beancount_plugins.check_valid_metadata" "/path/to/metadata_schema.yaml"

CONFIG FILE FORMAT:
Create a metadata_schema.yaml file with:

    metadata:
      transaction:
        source_payee:
          description: "Original payee name from import"
          type: string
          required: false
      posting:
        tag:
          description: "Posting-level categorization"
          type: string
          allowed_values: [personal, business]
      plugin_exceptions:
        - allowed_prefix: "_"
        - allowed_keys: [predicted_payee]

SCHEMA SPECIFICATION:

1. SECTION STRUCTURE:
   - metadata.transaction: Keys valid at transaction level
   - metadata.posting: Keys valid at posting level
   - metadata.plugin_exceptions: Skip validation for certain keys

2. KEY SPECIFICATION:
   - description: (string) Documentation of the field
   - type: (string) One of: string, int, bool, date, Decimal
   - required: (bool) If true, field must be present
   - allowed_values: (list) If present, value must be in this list
   - pattern: (string) Regex pattern for string values only
   - applies_to: (list) If present, key valid at specified levels
                        Can be: [transaction], [posting], or [transaction, posting]

3. PLUGIN EXCEPTIONS:
   - allowed_prefix: Any key starting with this is skipped (e.g., "_" for internal Beancount keys)
   - allowed_keys: Specific keys that bypass schema validation (e.g., smart_importer keys)

TYPE VALIDATION:
- string: isinstance(v, str)
- int: isinstance(v, int)
- bool: isinstance(v, bool)
- date: isinstance(v, datetime.date)
- Decimal: isinstance(v, Decimal)

ERROR REPORTING:
Errors are reported with field context:

    your-file.bean:42: Invalid metadata key 'unknown_key' on transaction
    your-file.bean:42: Invalid value 'invalid' for posting metadata 'tag' (allowed: personal, business)

COMPLEMENTARY PLUGINS:
- check_valid_tags: Validates transaction tags against allowed list
- check_missing_tags: Enforces required tags on specific accounts
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Tuple

import yaml
from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_valid_metadata",)


def check_valid_metadata(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> Tuple[data.Entries, List[ParserError]]:
    """Validate metadata keys and values against a typed schema.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config path (defaults to metadata_schema.yaml)

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors = []

    # Determine config file path
    if config:
        config_path = Path(config)
    else:
        ledger_dir = Path.cwd()
        config_path = ledger_dir / "metadata_schema.yaml"

    # Load configuration
    if not config_path.exists():
        error = ParserError(
            source={"filename": "metadata_schema.yaml", "lineno": 0},
            message=f"Metadata schema file not found: {config_path}",
            entry=None,
        )
        errors.append(error)
        logger.warning(f"Metadata schema file not found: {config_path}")
        return entries, errors

    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        error = ParserError(
            source={"filename": str(config_path), "lineno": 0},
            message=f"Failed to load metadata schema: {e}",
            entry=None,
        )
        errors.append(error)
        logger.error(f"Failed to load metadata schema: {e}")
        return entries, errors

    # Extract schema sections
    metadata_section = config_data.get("metadata", {})
    tx_schema = metadata_section.get("transaction", {})
    posting_schema = metadata_section.get("posting", {})
    exceptions = metadata_section.get("plugin_exceptions", [])

    # Build allowed keys and exception lists
    tx_allowed_keys = set(tx_schema.keys())
    posting_allowed_keys = set(posting_schema.keys())

    # Build exception rules
    allowed_prefixes = []
    allowed_exception_keys = set()
    for exception in exceptions:
        if isinstance(exception, dict):
            if "allowed_prefix" in exception:
                allowed_prefixes.append(exception["allowed_prefix"])
            if "allowed_keys" in exception:
                if isinstance(exception["allowed_keys"], list):
                    allowed_exception_keys.update(exception["allowed_keys"])

    logger.info(
        f"Loaded metadata schema: {len(tx_allowed_keys)} transaction keys, "
        f"{len(posting_allowed_keys)} posting keys"
    )

    # System keys always skipped
    system_keys = {"filename", "lineno"}

    violations_count = 0

    # Validate transactions and postings
    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Validate transaction-level metadata
        if entry.meta:
            for key, value in entry.meta.items():
                # Skip system keys
                if key in system_keys:
                    continue

                # Skip keys matching exception prefixes
                if any(key.startswith(p) for p in allowed_prefixes):
                    continue

                # Skip keys in allowed exceptions
                if key in allowed_exception_keys:
                    continue

                # Check if key is allowed
                if key not in tx_allowed_keys:
                    violations_count += 1
                    error = ParserError(
                        source={
                            "filename": entry.meta.get("filename", "unknown"),
                            "lineno": entry.meta.get("lineno", 0),
                        },
                        message=f"Invalid metadata key '{key}' on transaction",
                        entry=None,
                    )
                    errors.append(error)
                    continue

                # Validate value against schema
                value_error = _validate_metadata_value(
                    key, value, tx_schema[key], "transaction", entry
                )
                if value_error:
                    violations_count += 1
                    errors.append(value_error)

        # Validate posting-level metadata
        for posting in entry.postings:
            if posting.meta:
                for key, value in posting.meta.items():
                    # Skip system keys
                    if key in system_keys:
                        continue

                    # Skip keys matching exception prefixes
                    if any(key.startswith(p) for p in allowed_prefixes):
                        continue

                    # Skip keys in allowed exceptions
                    if key in allowed_exception_keys:
                        continue

                    # Check if key is allowed
                    if key not in posting_allowed_keys:
                        violations_count += 1
                        error = ParserError(
                            source={
                                "filename": entry.meta.get("filename", "unknown"),
                                "lineno": entry.meta.get("lineno", 0),
                            },
                            message=(
                                f"Invalid metadata key '{key}' on posting to "
                                f"'{posting.account}'"
                            ),
                            entry=None,
                        )
                        errors.append(error)
                        continue

                    # Validate value against schema
                    value_error = _validate_metadata_value(
                        key,
                        value,
                        posting_schema[key],
                        "posting",
                        entry,
                        posting.account,
                    )
                    if value_error:
                        violations_count += 1
                        errors.append(value_error)

    # Log summary
    if violations_count > 0:
        logger.warning(f"Found {violations_count} metadata validation errors")
    else:
        logger.info("All metadata is valid")

    return entries, errors


def _validate_metadata_value(
    key: str,
    value: Any,
    schema: dict,
    level: str,
    entry: data.Transaction,
    account: str | None = None,
) -> ParserError | None:
    """Validate a metadata value against its schema specification.

    Args:
        key: Metadata key name
        value: Metadata value
        schema: Schema specification for this key
        level: "transaction" or "posting"
        entry: The transaction entry
        account: Account name (for posting-level errors)

    Returns:
        ParserError if validation fails, None otherwise
    """
    # Check type constraint
    type_constraint = schema.get("type")
    if type_constraint and not _check_type(value, type_constraint):
        type_name = type_constraint
        actual_type = type(value).__name__
        msg = (
            f"Invalid type for {level} metadata '{key}': expected {type_name}, "
            f"got {actual_type}"
        )
        if account:
            msg += f" (posting to '{account}')"

        return ParserError(
            source={
                "filename": entry.meta.get("filename", "unknown"),
                "lineno": entry.meta.get("lineno", 0),
            },
            message=msg,
            entry=None,
        )

    # Check allowed_values constraint (only for strings)
    allowed_values = schema.get("allowed_values")
    if allowed_values and isinstance(value, str):
        if value not in allowed_values:
            allowed_str = ", ".join(str(v) for v in allowed_values)
            msg = (
                f"Invalid value '{value}' for {level} metadata '{key}' "
                f"(allowed: {allowed_str})"
            )
            if account:
                msg += f" (posting to '{account}')"

            return ParserError(
                source={
                    "filename": entry.meta.get("filename", "unknown"),
                    "lineno": entry.meta.get("lineno", 0),
                },
                message=msg,
                entry=None,
            )

    # Check pattern constraint (only for strings)
    pattern = schema.get("pattern")
    if pattern and isinstance(value, str):
        if not re.fullmatch(pattern, value):
            msg = (
                f"Invalid format for {level} metadata '{key}': '{value}' "
                f"does not match pattern '{pattern}'"
            )
            if account:
                msg += f" (posting to '{account}')"

            return ParserError(
                source={
                    "filename": entry.meta.get("filename", "unknown"),
                    "lineno": entry.meta.get("lineno", 0),
                },
                message=msg,
                entry=None,
            )

    return None


def _check_type(value: Any, type_name: str) -> bool:
    """Check if a value matches the specified type name.

    Args:
        value: The value to check
        type_name: Type name string (string, int, bool, date, Decimal)

    Returns:
        True if value matches the type
    """
    if type_name == "string":
        return isinstance(value, str)
    elif type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    elif type_name == "bool":
        return isinstance(value, bool)
    elif type_name == "date":
        return isinstance(value, date)
    elif type_name == "Decimal":
        return isinstance(value, Decimal)
    else:
        return False
