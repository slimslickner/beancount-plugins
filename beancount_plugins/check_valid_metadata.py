#!/usr/bin/env python3
"""Beancount plugin to validate metadata keys and values against a schema.

This plugin enforces a typed metadata schema across all directive types,
ensuring data quality and consistency. It validates metadata key names,
required vs. optional fields, and enforces type constraints and allowed values.

WHAT IT DOES:
- Loads metadata schema from a YAML configuration file
- Validates metadata on all directive types: Transaction, Open, Close, Document, Event, Note, Commodity
- Validates transaction-level metadata keys and values
- Validates posting-level metadata keys and values (transactions only)
- Enforces type constraints (string, int, bool, date, Decimal)
- Enforces allowed_values constraints
- Enforces pattern constraints (regex for strings)
- Enforces account_pattern constraints (scope required fields to matching accounts)
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
          label: "Original payee name from import"
          type: string
          required: false
        receipt_id:
          label: "Receipt reference"
          type: string
          required: true
          account_pattern: "Expenses:.*"  # Only required on Expenses accounts
      posting:
        tag:
          label: "Posting-level categorization"
          type: string
          allowed_values: [personal, business]
      open:
        tag-expected:
          label: "If true, transactions posting to this account require tags"
          type: bool
      close:
        reason:
          label: "Reason for closing account"
          type: string
      document:
        verified:
          label: "Whether document has been verified"
          type: bool
      event:
        category:
          label: "Event category"
          type: string
      commodity:
        name:
          label: "Human-readable name of commodity"
          type: string
        cusip:
          label: "CUSIP identifier"
          type: string
      note:
        importance:
          label: "Note importance level"
          type: string
          allowed_values: [low, medium, high]
      plugin_exceptions:
        - allowed_prefix: "_"
        - allowed_keys: [predicted_payee]

SCHEMA SPECIFICATION:

1. SECTION STRUCTURE:
   - metadata.transaction: Keys valid at transaction level
   - metadata.posting: Keys valid at posting level (transactions only)
   - metadata.open: Keys valid on Open directives
   - metadata.close: Keys valid on Close directives
   - metadata.document: Keys valid on Document directives
   - metadata.event: Keys valid on Event directives
   - metadata.commodity: Keys valid on Commodity directives
   - metadata.note: Keys valid on Note directives
   - metadata.plugin_exceptions: Skip validation for certain keys

2. KEY SPECIFICATION:
   - label: (string) Documentation of the field
   - type: (string) One of: string, int, bool, date, Decimal
   - required: (bool) If true, field must be present
   - account_pattern: (string) Regex pattern to scope required fields to matching accounts
   - allowed_values: (list) If present, value must be in this list
   - pattern: (string) Regex pattern for string values only

3. ACCOUNT PATTERN:
   When account_pattern is set on a required field:
   - For transaction-level metadata: required only if ANY posting account matches
   - For posting-level metadata: required only if the specific posting account matches
   - Uses re.fullmatch() for exact matching (e.g., "Expenses:.*" matches all Expenses)
   - If account_pattern is not set, the field is universally required

4. PLUGIN EXCEPTIONS:
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
    your-file.bean:15: Invalid metadata key 'unknown_key' on Open directive for 'Assets:Checking'

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
from typing import Any

import yaml
from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("check_valid_metadata",)

# System keys always skipped during validation
_SYSTEM_KEYS = {"filename", "lineno"}


def _compile_spec(spec: dict) -> dict:
    """Compile regex strings and convert allowed_values to frozenset in a spec dict.

    Called once at schema-load time so per-entry validation never re-compiles.
    """
    compiled = dict(spec)
    raw_ap = compiled.get("account_pattern")
    if isinstance(raw_ap, str):
        compiled["account_pattern"] = re.compile(raw_ap)
    raw_pat = compiled.get("pattern")
    if isinstance(raw_pat, str):
        compiled["pattern"] = re.compile(raw_pat)
    raw_av = compiled.get("allowed_values")
    if isinstance(raw_av, list):
        compiled["allowed_values"] = frozenset(raw_av)
    return compiled


def check_valid_metadata(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> tuple[data.Entries, list[ParserError]]:
    """Validate metadata keys and values against a typed schema.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional config path (defaults to metadata_schema.yaml)

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
        config_path = ledger_dir / "metadata_schema.yaml"

    # Load configuration
    if not config_path.exists():
        error = ParserError(
            source={"filename": "metadata_schema.yaml", "lineno": 0},
            message=f"Metadata schema file not found: {config_path}",
            entry=None,
        )
        errors.append(error)
        logger.warning("Metadata schema file not found: %s", config_path)
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
        logger.error("Failed to load metadata schema: %s", e)
        return entries, errors

    # Extract schema sections, compiling regex patterns and allowed_values once
    metadata_section = config_data.get("metadata", {})
    _dtypes = (
        "transaction",
        "posting",
        "open",
        "close",
        "document",
        "event",
        "commodity",
        "note",
    )
    directive_schemas: dict[str, dict[str, dict]] = {
        dtype: {
            k: _compile_spec(spec) if isinstance(spec, dict) else spec
            for k, spec in (metadata_section.get(dtype) or {}).items()
        }
        for dtype in _dtypes
    }
    exceptions = metadata_section.get("plugin_exceptions", [])

    # Build allowed keys for each directive type
    allowed_keys = {
        key: set(schema.keys()) for key, schema in directive_schemas.items()
    }

    # Build required keys for each directive type (key -> compiled spec dict)
    required_specs: dict[str, dict[str, dict]] = {
        dtype: {
            k: spec
            for k, spec in schema.items()
            if isinstance(spec, dict) and spec.get("required") is True
        }
        for dtype, schema in directive_schemas.items()
    }

    # Build exception rules
    allowed_prefixes: list[str] = []
    allowed_exception_keys: set[str] = set()
    for exception in exceptions:
        if isinstance(exception, dict):
            if "allowed_prefix" in exception:
                allowed_prefixes.append(exception["allowed_prefix"])
            if "allowed_keys" in exception:
                if isinstance(exception["allowed_keys"], list):
                    allowed_exception_keys.update(exception["allowed_keys"])

    logger.info(
        "Loaded metadata schema: %d keys across %d directive types",
        sum(len(s) for s in directive_schemas.values()),
        len([s for s in directive_schemas.values() if s]),
    )

    violations_count = 0

    # Validate all directive types
    for entry in entries:
        # Determine directive type and get schema
        if isinstance(entry, data.Transaction):
            directive_type = "transaction"
        elif isinstance(entry, data.Open):
            directive_type = "open"
        elif isinstance(entry, data.Close):
            directive_type = "close"
        elif isinstance(entry, data.Document):
            directive_type = "document"
        elif isinstance(entry, data.Event):
            directive_type = "event"
        elif isinstance(entry, data.Commodity):
            directive_type = "commodity"
        elif isinstance(entry, data.Note):
            directive_type = "note"
        else:
            continue

        schema = directive_schemas.get(directive_type, {})
        context = _get_directive_context(entry, directive_type)
        source = {
            "filename": entry.meta.get("filename", "unknown")
            if entry.meta
            else "unknown",
            "lineno": entry.meta.get("lineno", 0) if entry.meta else 0,
        }

        # Validate directive-level metadata keys and values
        key_errors = _validate_metadata_keys(
            meta=entry.meta,
            allowed=allowed_keys[directive_type],
            schema=schema,
            level=directive_type,
            source=source,
            context=context,
            allowed_prefixes=allowed_prefixes,
            allowed_exception_keys=allowed_exception_keys,
        )
        violations_count += len(key_errors)
        errors.extend(key_errors)

        # Check for missing required directive-level metadata
        present_keys = set(entry.meta.keys()) - _SYSTEM_KEYS if entry.meta else set()
        if isinstance(entry, data.Transaction):
            accounts = [p.account for p in entry.postings]
        elif isinstance(entry, (data.Open, data.Close, data.Document)):
            accounts = [entry.account]
        else:
            accounts = []
        for req_key, req_spec in required_specs[directive_type].items():
            if req_key in present_keys:
                continue
            if not _account_pattern_matches(req_spec, accounts):
                continue
            violations_count += 1
            errors.append(
                ParserError(
                    source=source,
                    message=f"Missing required metadata '{req_key}' on {directive_type} directive{context}",
                    entry=None,
                )
            )

        # Validate posting-level metadata (transactions only)
        if isinstance(entry, data.Transaction):
            for posting in entry.postings:
                posting_context = f" (posting to '{posting.account}')"

                key_errors = _validate_metadata_keys(
                    meta=posting.meta,
                    allowed=allowed_keys["posting"],
                    schema=directive_schemas["posting"],
                    level="posting",
                    source=source,
                    context=posting_context,
                    allowed_prefixes=allowed_prefixes,
                    allowed_exception_keys=allowed_exception_keys,
                )
                violations_count += len(key_errors)
                errors.extend(key_errors)

                # Check for missing required posting-level metadata
                posting_present = (
                    set(posting.meta.keys()) - _SYSTEM_KEYS if posting.meta else set()
                )
                for req_key, req_spec in required_specs["posting"].items():
                    if req_key in posting_present:
                        continue
                    if not _account_pattern_matches(req_spec, [posting.account]):
                        continue
                    violations_count += 1
                    errors.append(
                        ParserError(
                            source=source,
                            message=f"Missing required metadata '{req_key}' on posting to '{posting.account}'",
                            entry=None,
                        )
                    )

    # Log summary
    if violations_count > 0:
        logger.warning("Found %d metadata validation errors", violations_count)
    else:
        logger.info("All metadata is valid")

    return entries, errors


def _validate_metadata_keys(
    meta: dict | None,
    allowed: set[str],
    schema: dict,
    level: str,
    source: dict,
    context: str,
    allowed_prefixes: list[str],
    allowed_exception_keys: set[str],
) -> list[ParserError]:
    """Validate metadata keys and values against schema.

    Checks each key in meta against allowed keys and exception rules,
    then validates values against schema constraints.

    Args:
        meta: Metadata dict to validate (may be None)
        allowed: Set of allowed key names for this level
        schema: Schema dict for value validation
        level: Directive type name (for error messages)
        source: Pre-built source dict (filename/lineno) for error reporting
        context: Additional context string for error messages
        allowed_prefixes: Prefixes that bypass validation
        allowed_exception_keys: Specific keys that bypass validation

    Returns:
        List of ParserError for any violations found
    """
    if not meta:
        return []

    errors: list[ParserError] = []

    for key, value in meta.items():
        if key in _SYSTEM_KEYS:
            continue
        if any(key.startswith(p) for p in allowed_prefixes):
            continue
        if key in allowed_exception_keys:
            continue

        if key not in allowed:
            errors.append(
                ParserError(
                    source=source,
                    message=f"Invalid metadata key '{key}' on {level} directive{context}",
                    entry=None,
                )
            )
            continue

        value_error = _validate_metadata_value(
            key, value, schema[key], level, source, context
        )
        if value_error:
            errors.append(value_error)

    return errors


def _account_pattern_matches(spec: dict, accounts: list[str]) -> bool:
    """Check if any account matches the spec's account_pattern.

    If the spec has no account_pattern, returns True (universally required).
    Otherwise, returns True only if at least one account matches the pattern.

    Args:
        spec: Compiled schema spec dict; account_pattern is a re.Pattern or absent
        accounts: List of account names to check

    Returns:
        True if the requirement applies
    """
    pattern: re.Pattern | None = spec.get("account_pattern")
    if not pattern:
        return True
    return any(pattern.fullmatch(account) for account in accounts)


def _get_directive_context(entry: data.Directive, directive_type: str) -> str:
    """Get a context string describing the directive.

    Args:
        entry: The directive entry
        directive_type: Type of directive (open, close, document, event, commodity, note, transaction)

    Returns:
        Context string for error messages
    """
    if directive_type in {"open", "close"}:
        if isinstance(entry, (data.Open, data.Close)):
            return f" for '{entry.account}'"
    elif directive_type == "document":
        if isinstance(entry, data.Document):
            return f" for '{entry.account}' (filename: {entry.filename})"
    elif directive_type == "event":
        if isinstance(entry, data.Event):
            return f" (type: {entry.type})"
    elif directive_type == "commodity":
        if isinstance(entry, data.Commodity):
            return f" for '{entry.currency}'"
    return ""


def _validate_metadata_value(
    key: str,
    value: Any,
    schema: dict,
    level: str,
    source: dict,
    context: str = "",
) -> ParserError | None:
    """Validate a metadata value against its schema specification.

    Args:
        key: Metadata key name
        value: Metadata value
        schema: Compiled schema specification for this key
        level: Directive type (transaction, posting, open, close, document, event, note)
        source: Pre-built source dict (filename/lineno) for error reporting
        context: Additional context for error messages

    Returns:
        ParserError if validation fails, None otherwise
    """
    # Check type constraint
    type_constraint = schema.get("type")
    if type_constraint and not _check_type(value, type_constraint):
        actual_type = type(value).__name__
        msg = (
            f"Invalid type for {level} metadata '{key}': expected {type_constraint}, "
            f"got {actual_type}"
        )
        if context:
            msg += context
        return ParserError(source=source, message=msg, entry=None)

    # Check allowed_values constraint (only for strings); frozenset after _compile_spec
    allowed_values: frozenset | None = schema.get("allowed_values")
    if allowed_values and isinstance(value, str):
        if value not in allowed_values:
            msg = f"Invalid value '{value}' for {level} metadata '{key}'"
            if context:
                msg += context
            return ParserError(source=source, message=msg, entry=None)

    # Check pattern constraint (only for strings); re.Pattern after _compile_spec
    pattern: re.Pattern | None = schema.get("pattern")
    if pattern and isinstance(value, str):
        if not pattern.fullmatch(value):
            msg = (
                f"Invalid format for {level} metadata '{key}': '{value}' "
                f"does not match pattern '{pattern.pattern}'"
            )
            if context:
                msg += context
            return ParserError(source=source, message=msg, entry=None)

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
