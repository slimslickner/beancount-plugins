#!/usr/bin/env python3
"""Beancount plugin to validate metadata keys and values against a schema.

This plugin enforces a typed metadata schema across all directive types,
ensuring data quality and consistency. It validates metadata key names,
required vs. optional fields, and enforces type constraints and allowed values.

WHAT IT DOES:
- Loads metadata schema from a YAML configuration file or an inline dict literal
- Validates metadata on all directive types: Transaction, Open, Close, Document, Event, Note, Commodity
- Validates transaction-level metadata keys and values
- Validates posting-level metadata keys and values (transactions only)
- Enforces type constraints (string, int, bool, date, Decimal)
- Enforces allowed_values constraints
- Enforces pattern constraints (regex for strings)
- Enforces account_pattern constraints (fields are only allowed on matching accounts)
- Errors on declared-but-unused keys: any key in the schema that never appears
  on a matching directive (or posting) is reported as stale/dead config
- Reports violations as parser errors with field context

USAGE:
In your main ledger file:
    plugin "beancount_plugins.check_valid_metadata"

Optional config. The second argument is dual-mode: it may be a path to a
metadata_schema.yaml file, OR an inline Python dict literal mirroring the
file's shape. The mode is chosen by a simple rule — if the argument (after
stripping whitespace) starts with '{', it is parsed as an inline dict;
otherwise it is treated as a file path.

Alternate config file:
    plugin "beancount_plugins.check_valid_metadata" "/path/to/metadata_schema.yaml"

Inline config (Python dict literal, top-level 'metadata' key required):
    plugin "beancount_plugins.check_valid_metadata" "{
        'metadata': {
            'posting': {
                'tag': {
                    'label': 'Posting-level categorization',
                    'type': 'string',
                    'allowed_values': ['personal', 'business']
                }
            }
        }
    }"

The inline dict uses Python literal syntax (parsed via ast.literal_eval):
single or double quotes, and booleans as True/False — not YAML/JSON's
true/false. Small schemas can live in the ledger; a YAML file remains the
better option for large schemas (this author's is ~490 lines).

DEFAULT:
When no config is given, metadata_schema.yaml is loaded from the ledger
file's directory.

CONFIG FILE FORMAT:
Create a metadata_schema.yaml file with:

    metadata:
      transaction:
        source_payee:
          label: "Original payee name from import"
          type: string
          required: false
      posting:
        tag:
          label: "Posting-level categorization"
          type: string
          allowed_values: [personal, business]
        receipt_id:
          label: "Receipt reference"
          type: string
          required: true
          account_pattern: "Expenses:.*"  # Only allowed/required on Expenses postings
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
   - account_pattern: (string) Regex pattern restricting the field to matching accounts
     (only valid on posting, open, close, document, and note sections)
   - allowed_values: (list) If present, value must be in this list
   - pattern: (string) Regex pattern for string values only

3. ACCOUNT PATTERN:
    account_pattern scopes a field to matching accounts. It is only allowed on
    account-scoped sections: posting, open, close, document, and note. Declaring
    it on transaction, event, or commodity is a configuration error.

    When account_pattern is set on a field:
    - The field is ONLY allowed where the account matches. Present on a
      non-matching account -> error.
    - If required is also true, the field is required only where the account
      matches:
      - For posting-level metadata: matches the specific posting account
      - For open/close/document/note: matches the directive's account
    - Uses re.match() so the pattern matches from the start of the account name
      up to a whole account-component boundary (before a ':' or end of string).
      Examples:
      - "Expenses" matches "Expenses" and "Expenses:Groceries",
        but not "ExpensesChase"
      - "^(Expenses|Liabilities:Loans)" matches "Expenses",
        "Expenses:Groceries", "Liabilities:Loans", and "Liabilities:Loans:Chase",
        but not "Liabilities:LoansChase"
      - "^Assets:(?!Property:)" matches "Assets:Investment:Brokerage",
        "Assets:Checking", etc., but not "Assets:Property:House"
      A pattern may consume the trailing ':' separator; the match is accepted as
      long as it ends at a component boundary.
    - If account_pattern is not set, the field may appear anywhere (and is
      universally required when required is true)

4. PLUGIN EXCEPTIONS:
   - allowed_prefix: Any key starting with this is skipped (e.g., "_" for internal Beancount keys)
   - allowed_keys: Specific keys that bypass schema validation (e.g., smart_importer keys)

5. UNUSED KEY CHECK:
   Every key declared in a section must be used at least once, otherwise a
   ParserError is emitted at schema-load time. "Used" means the key appears on a
   directive (or posting) of the section it is declared in:
   - transaction keys must appear on at least one Transaction directive
   - posting keys must appear on at least one posting
   - open/close/document/event/commodity/note keys must appear on at least one
     matching directive
   For a key with account_pattern, only occurrences on a matching account count;
   an occurrence on a non-matching account is already an error and does not
   satisfy the usage requirement. Keys matched by plugin_exceptions bypass
   validation; a key that is both declared and excepted still counts as used.

   NOTE: this check is unconditional. A schema loaded against a ledger with no
   matching directives will report every declared key as unused.

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
    your-file.bean:42: Metadata 'receipt_id' on posting directive (posting to 'Expenses:Travel') is only allowed on accounts matching 'Expenses:Reimbursable'

Declared-but-unused keys are reported against the ledger file at line 0
(file-level, since there is no offending directive to point at):

    your-file.bean:0: check_valid_metadata: Declared metadata key 'obsolete_field' in 'transaction' schema is never used

COMPLEMENTARY PLUGINS:
- check_valid_tags: Validates transaction tags against allowed list
- check_missing_tags: Enforces required tags on specific accounts
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import ast
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

# Schema sections on which account_pattern is meaningful (directives with an account)
_ACCOUNT_PATTERN_LEVELS = ("posting", "open", "close", "document", "note")

# Label used as the ParserError source for inline-config problems.
_INLINE_CONFIG_LABEL = "plugin config"


def _load_config(
    config: str | None,
    ledger_dir: Path,
) -> tuple[dict[str, Any], str, list[ParserError]]:
    """Load metadata schema config from either an inline dict or a YAML file path.

    The second plugin argument is dual-mode: if it starts with '{' it is parsed
    as an inline Python dict literal; otherwise it is treated as a path to a
    metadata_schema.yaml file (resolved relative to the ledger directory when
    relative). When no config is supplied, metadata_schema.yaml is loaded from
    the ledger directory.

    Returns (config_data, config_label, errors). config_label names the config
    source for schema-level error messages. On error config_data is an empty
    dict and the caller should return the entries unchanged.
    """
    errors: list[ParserError] = []

    if config and config.strip().startswith("{"):
        try:
            parsed: Any = ast.literal_eval(config)
        except (ValueError, SyntaxError) as e:
            errors.append(
                ParserError(
                    source={"filename": _INLINE_CONFIG_LABEL, "lineno": 0},
                    message=(
                        f"check_valid_metadata: Invalid inline config: {e}. "
                        "Use Python literal syntax (single or double quotes, "
                        "True/False — not YAML/JSON true/false)."
                    ),
                    entry=None,
                )
            )
            return {}, _INLINE_CONFIG_LABEL, errors

        if not isinstance(parsed, dict):
            errors.append(
                ParserError(
                    source={"filename": _INLINE_CONFIG_LABEL, "lineno": 0},
                    message=(
                        "check_valid_metadata: config must be a dict, "
                        f"got {type(parsed).__name__}"
                    ),
                    entry=None,
                )
            )
            return {}, _INLINE_CONFIG_LABEL, errors

        metadata_section = parsed.get("metadata")
        if metadata_section is not None and not isinstance(metadata_section, dict):
            errors.append(
                ParserError(
                    source={"filename": _INLINE_CONFIG_LABEL, "lineno": 0},
                    message=(
                        "check_valid_metadata: 'metadata' must be a dict of "
                        f"sections, got {type(metadata_section).__name__}"
                    ),
                    entry=None,
                )
            )
            return {}, _INLINE_CONFIG_LABEL, errors

        return parsed, _INLINE_CONFIG_LABEL, errors

    # Not an inline dict. Guard against config strings that plainly cannot be
    # file paths: a stray literal (e.g. a YAML block pasted inline, or an inline
    # schema whose leading '{' was lost) would otherwise be handed to the
    # filesystem, where Path.exists()/open() raise OSError(ENAMETOOLONG) on some
    # platforms and abort the whole plugin with an opaque traceback. Only the
    # component check matches the OS limit, so long-but-valid absolute paths
    # still work.
    if config:
        _parts = config.replace("\\", "/").split("/")
        if "\n" in config or any(len(part) > 255 for part in _parts):
            errors.append(
                ParserError(
                    source={"filename": _INLINE_CONFIG_LABEL, "lineno": 0},
                    message=(
                        "check_valid_metadata: config is neither a valid inline "
                        "dict literal nor a usable file path (it contains newlines "
                        "or a path component over 255 characters). Use an inline "
                        "Python dict literal starting with '{', or a path to "
                        "metadata_schema.yaml."
                    ),
                    entry=None,
                )
            )
            return {}, _INLINE_CONFIG_LABEL, errors

    # File-path mode (default or explicit).
    if config:
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = ledger_dir / config_path
    else:
        config_path = ledger_dir / "metadata_schema.yaml"

    try:
        if not config_path.exists():
            errors.append(
                ParserError(
                    source={"filename": "metadata_schema.yaml", "lineno": 0},
                    message=f"Metadata schema file not found: {config_path}",
                    entry=None,
                )
            )
            logger.warning("Metadata schema file not found: %s", config_path)
            return {}, str(config_path), errors

        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        errors.append(
            ParserError(
                source={"filename": str(config_path), "lineno": 0},
                message=f"Failed to load metadata schema: {e}",
                entry=None,
            )
        )
        logger.error("Failed to load metadata schema: %s", e)
        return {}, str(config_path), errors

    return config_data, str(config_path), errors


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
        config: Optional dual-mode config — an inline Python dict literal (must
            start with '{' and carry a top-level 'metadata' key) or a path to a
            metadata_schema.yaml file. Defaults to metadata_schema.yaml in the
            ledger directory.

    Returns:
        Tuple of (entries_unchanged, errors)
    """
    errors: list[ParserError] = []

    # Load configuration: inline dict literal or metadata_schema.yaml file path.
    ledger_filename = options_map.get("filename", "unknown")
    ledger_dir = Path(options_map.get("filename", "")).parent
    config_data, config_label, config_errors = _load_config(config, ledger_dir)
    if config_errors:
        return entries, config_errors

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

    # Validate schema: account_pattern is only meaningful on account-scoped
    # sections. Report every misdeclaration at load time before validating entries.
    schema_errors: list[ParserError] = []
    for dtype in _dtypes:
        if dtype in _ACCOUNT_PATTERN_LEVELS:
            continue
        for key, spec in directive_schemas[dtype].items():
            if isinstance(spec, dict) and "account_pattern" in spec:
                schema_errors.append(
                    ParserError(
                        source={"filename": config_label, "lineno": 0},
                        message=(
                            f"account_pattern is not valid on '{dtype}' metadata "
                            f"'{key}': account_pattern only applies to "
                            f"{', '.join(_ACCOUNT_PATTERN_LEVELS)}"
                        ),
                        entry=None,
                    )
                )
    if schema_errors:
        errors.extend(schema_errors)
        logger.warning("Found %d account_pattern schema errors", len(schema_errors))
        return entries, errors

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

    # Track which declared keys are actually used, per section. A key counts as
    # used only when it appears on a directive/posting of its declared section
    # and (for account_pattern keys) on a matching account.
    used_keys: dict[str, set[str]] = {dtype: set() for dtype in _dtypes}

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

    logger.debug(
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
        accounts = _entry_accounts(entry)
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
            accounts=accounts,
            allowed_prefixes=allowed_prefixes,
            allowed_exception_keys=allowed_exception_keys,
            used=used_keys[directive_type],
        )
        violations_count += len(key_errors)
        errors.extend(key_errors)

        # Check for missing required directive-level metadata
        present_keys = set(entry.meta.keys()) - _SYSTEM_KEYS if entry.meta else set()
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
                    accounts=[posting.account],
                    allowed_prefixes=allowed_prefixes,
                    allowed_exception_keys=allowed_exception_keys,
                    used=used_keys["posting"],
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

    # Report declared-but-unused keys: any schema key that never appeared on a
    # matching directive (or posting) of its declared section is dead config.
    # Anchored to the ledger file at line 0 (file-level) since an unused key has
    # no offending directive to point at.
    unused_source = {"filename": ledger_filename, "lineno": 0}
    for dtype in _dtypes:
        unused = sorted(set(directive_schemas[dtype]) - used_keys[dtype])
        for key in unused:
            violations_count += 1
            errors.append(
                ParserError(
                    source=dict(unused_source),
                    message=(
                        f"check_valid_metadata: Declared metadata key '{key}' in "
                        f"'{dtype}' schema is never used"
                    ),
                    entry=None,
                )
            )

    # Log summary
    if violations_count > 0:
        logger.warning("Found %d metadata validation errors", violations_count)
    else:
        logger.debug("All metadata is valid")

    return entries, errors


def _validate_metadata_keys(
    meta: dict | None,
    allowed: set[str],
    schema: dict,
    level: str,
    source: dict,
    context: str,
    accounts: list[str],
    allowed_prefixes: list[str],
    allowed_exception_keys: set[str],
    used: set[str],
) -> list[ParserError]:
    """Validate metadata keys and values against schema.

    Checks each key in meta against allowed keys and exception rules,
    then validates values against schema constraints. Keys with an
    account_pattern are only allowed where one of the accounts matches.

    Args:
        meta: Metadata dict to validate (may be None)
        allowed: Set of allowed key names for this level
        schema: Schema dict for value validation
        level: Directive type name (for error messages)
        source: Pre-built source dict (filename/lineno) for error reporting
        context: Additional context string for error messages
        accounts: Account names the metadata applies to (for account_pattern)
        allowed_prefixes: Prefixes that bypass validation
        allowed_exception_keys: Specific keys that bypass validation
        used: Set of declared keys observed as used; mutated in place. A key is
            added only when it is declared, passes the account_pattern check,
            and so genuinely satisfies its section's usage requirement.

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
            # Exception keys bypass schema validation, but if one is also
            # declared in the schema it is still used and must not be reported
            # as stale config.
            if key in allowed:
                used.add(key)
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

        spec = schema[key]
        pattern: re.Pattern | None = spec.get("account_pattern")
        if pattern and not _account_pattern_matches(spec, accounts):
            errors.append(
                ParserError(
                    source=source,
                    message=(
                        f"Metadata '{key}' on {level} directive{context} is only "
                        f"allowed on accounts matching '{pattern.pattern}'"
                    ),
                    entry=None,
                )
            )
            continue

        # Declared key present on a matching directive: it is used.
        used.add(key)

        value_error = _validate_metadata_value(key, value, spec, level, source, context)
        if value_error:
            errors.append(value_error)

    return errors


def _account_pattern_matches(spec: dict, accounts: list[str]) -> bool:
    """Check if any account matches the spec's account_pattern.

    Used both to decide whether a required field must be present and whether
    a patterned field is allowed. If the spec has no account_pattern, returns
    True (universally allowed/required). Otherwise, returns True if at least
    one account matches the pattern from the start of the account name up to a
    whole account-component boundary (end of string, just before a ':', or
    just after a ':' when the pattern consumes the separator).

    Args:
        spec: Compiled schema spec dict; account_pattern is a re.Pattern or absent
        accounts: List of account names to check

    Returns:
        True if the pattern applies (or no pattern is set)
    """
    pattern: re.Pattern | None = spec.get("account_pattern")
    if not pattern:
        return True
    for account in accounts:
        match = pattern.match(account)
        if not match:
            continue
        # The matched prefix must end at a whole component, not in the
        # middle of an account component like 'Liabilities:LoansChase'.
        # A boundary is end-of-string, a ':' immediately after the match, or
        # a ':' as the match's last character (e.g. a pattern ending in ':').
        end = match.end()
        if end == len(account) or account[end] == ":":
            return True
        if end > 0 and account[end - 1] == ":":
            return True
    return False


def _entry_accounts(entry: data.Directive) -> list[str]:
    """Return the account names a directive's metadata applies to.

    Transactions span many postings; account-scoped directives carry a single
    account; the rest have none.

    Args:
        entry: The directive entry

    Returns:
        List of account names (empty when the directive has no account)
    """
    if isinstance(entry, data.Transaction):
        return [p.account for p in entry.postings]
    if isinstance(entry, (data.Open, data.Close, data.Document, data.Note)):
        return [entry.account]
    return []


def _get_directive_context(entry: data.Directive, directive_type: str) -> str:
    """Get a context string describing the directive.

    Args:
        entry: The directive entry
        directive_type: Type of directive (open, close, document, event, commodity, note, transaction)

    Returns:
        Context string for error messages
    """
    if directive_type in {"open", "close", "note"}:
        if isinstance(entry, (data.Open, data.Close, data.Note)):
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
