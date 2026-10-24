#!/usr/bin/env python3
"""Beancount plugin to derive aggregated metadata on Open directives.

Given a source metadata key on an Open directive (e.g. `account-type`), this
plugin reads its value and writes one or more derived metadata keys back onto
the same Open directive, based on a user-supplied value -> value mapping.

This is Open-directive-only: metadata is read from the Open directive and
written back to the Open directive. Combine with `promote_account_metadata`
(loaded AFTER this plugin) to flow the derived keys down to postings.

WHAT IT DOES:
- Parses an inline Python-dict config describing one or more aggregations
- Phase 1: validates the config (shape, unknown keys, overlaps, mode rules)
- Phase 2: for each Open directive carrying the source key, maps its value to
  the derived key and writes it back onto the same Open's metadata
- Phase 3: coverage checks — uncovered source values (strict mode) and
  declared-but-never-used source values (both modes) produce ParserErrors

USAGE:
Load before promote_account_metadata and check_valid_metadata:

    plugin "beancount_plugins.aggregate_account_metadata" "{
        'aggregations': {
            'asset-class': {
                'source': 'account-type',
                'mode': 'strict',
                'maps': {
                    'taxable':        ['checking', 'savings', 'money-market',
                                       'transfer', 'brokerage'],
                    'retirement':     ['ira', '401a', '401k', '403b', '457b',
                                       'pension', 'defined-contribution'],
                    'tax-advantaged': ['hsa', 'fsa', '530a', '529'],
                    'liability':      ['credit-card', 'student-loan', 'mortgage'],
                    'property':       ['home', 'vehicle']
                }
            }
        }
    }"

CONFIG KEYS:
Top level:
- aggregations: (dict, required, non-empty) maps the NEW metadata key name to
  an aggregation spec.

Per aggregation spec:
- source: (string, required) the source metadata key to read.
- mode: (string, optional, default 'strict') either 'strict' or 'default'.
    - 'strict': every source value observed on an Open must be listed in
      `maps`, otherwise a ParserError is emitted at that Open's file/line.
    - 'default': a `default` must be provided; source values not listed in
      `maps` are mapped to `default` (no error).
- default: (string or bool) the fallback derived value. REQUIRED when mode is
  'default'; disallowed when mode is 'strict'.
- maps: (dict, required, non-empty) maps an aggregated value (string or bool)
  to a list of source values (strings). A source value may not appear in more
  than one aggregated value's list within the same aggregation.

COVERAGE CHECKS (per aggregation):
- Uncovered source value: in 'strict' mode, an observed source value that is
  not present in `maps` is a ParserError on the offending Open.
- Unused declaration: any source value declared in `maps` that is never
  observed on any Open is a ParserError regardless of mode. This catches stale
  mappings when accounts are renamed or removed.

CONFLICT RESOLUTION:
If an Open already carries the derived key, the existing value is preserved
and a WARNING is logged (visible with `bean-check -v`). This mirrors
promote_account_metadata's conflict behavior.

EXAMPLE:

    2026-01-01 open Assets:Banking:Checking USD
      account-type: "checking"

    After processing, the Open directive gains:

      account-type: "checking"
      asset-class: "taxable"

A derived value may also be a boolean:

    plugin "beancount_plugins.aggregate_account_metadata" "{
        'aggregations': {
            'taxable': {
                'source': 'account-type',
                'mode': 'strict',
                'maps': {
                    True:  ['checking', 'savings', 'brokerage'],
                    False: ['ira', '401k', 'mortgage']
                }
            }
        }
    }"

PLUGIN LOAD ORDER:
- Load BEFORE promote_account_metadata so derived keys flow down to postings.
- Load BEFORE check_valid_metadata; add derived keys to the `open:` section of
  metadata_schema.yaml, otherwise they will be flagged as unknown.
"""

__copyright__ = "Copyright (C) 2026 slimslickner"
__license__ = "GNU GPLv2"

import ast
import logging
from dataclasses import dataclass
from typing import Any

from beancount.core import data
from beancount.parser.parser import ParserError

logger = logging.getLogger(__name__)

__plugins__ = ("aggregate_account_metadata",)

_ALLOWED_TOP_KEYS: frozenset[str] = frozenset({"aggregations"})
_ALLOWED_AGG_KEYS: frozenset[str] = frozenset(
    {"source", "mode", "default", "maps"}
)
_VALID_MODES: frozenset[str] = frozenset({"strict", "default"})
_DEFAULT_MODE: str = "strict"

_CONFIG_SOURCE: dict[str, Any] = {"filename": "plugin config", "lineno": 0}

# Derived metadata values written onto Open directives. Source values are always
# strings; the derived (aggregated) value may be a string or a boolean.
MetadataValue = str | bool


@dataclass
class AggregationSpec:
    """A single parsed aggregation: derived key + source + value mapping."""

    key: str
    source: str
    mode: str
    default: MetadataValue | None
    value_map: dict[str, MetadataValue]
    declared_values: frozenset[str]


def _coerce_string_list(
    raw: Any,
    context: str,
    errors: list[ParserError],
) -> tuple[str, ...] | None:
    """Normalize a string-or-list value to a tuple, or None on type error."""
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(p, str) for p in raw):
        return tuple(raw)
    errors.append(
        ParserError(
            source=dict(_CONFIG_SOURCE),
            message=(
                f"aggregate_account_metadata: {context} must be "
                f"a string or list of strings"
            ),
            entry=None,
        )
    )
    return None


def _parse_aggregation(
    key: Any,
    spec: Any,
    errors: list[ParserError],
) -> AggregationSpec | None:
    """Parse and validate a single aggregation spec.

    Returns the spec, or None if it is invalid (errors are appended).
    """
    if not isinstance(key, str) or not key:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    "aggregate_account_metadata: aggregation key must be "
                    "a non-empty string"
                ),
                entry=None,
            )
        )
        return None

    if not isinstance(spec, dict):
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: aggregation '{key}' must be a dict"
                ),
                entry=None,
            )
        )
        return None

    unknown = set(spec.keys()) - _ALLOWED_AGG_KEYS
    if unknown:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: aggregation '{key}' has unknown "
                    f"keys: {', '.join(sorted(unknown))}. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_AGG_KEYS))}"
                ),
                entry=None,
            )
        )
        return None

    source = spec.get("source")
    if not isinstance(source, str) or not source:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: aggregation '{key}' requires a "
                    f"non-empty 'source' string"
                ),
                entry=None,
            )
        )
        return None

    mode = spec.get("mode", _DEFAULT_MODE)
    if mode not in _VALID_MODES:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: aggregation '{key}' has invalid "
                    f"mode '{mode}'. Allowed: {', '.join(sorted(_VALID_MODES))}"
                ),
                entry=None,
            )
        )
        return None

    raw_maps = spec.get("maps")
    if not isinstance(raw_maps, dict) or not raw_maps:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: aggregation '{key}' requires a "
                    f"non-empty 'maps' dict"
                ),
                entry=None,
            )
        )
        return None

    value_map: dict[str, MetadataValue] = {}
    overlaps: set[str] = set()
    for agg_value, raw_source_values in raw_maps.items():
        if not isinstance(agg_value, (str, bool)) or (
            isinstance(agg_value, str) and not agg_value
        ):
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        f"aggregate_account_metadata: aggregation '{key}' has a "
                        f"non-string/bool or empty aggregated value"
                    ),
                    entry=None,
                )
            )
            return None
        coerced = _coerce_string_list(
            raw_source_values,
            f"aggregation '{key}' map '{agg_value}'",
            errors,
        )
        if coerced is None:
            return None
        for src_value in coerced:
            if src_value in value_map:
                overlaps.add(src_value)
            else:
                value_map[src_value] = agg_value

    if overlaps:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: aggregation '{key}' maps source "
                    f"value(s) to multiple outputs: {', '.join(sorted(overlaps))}"
                ),
                entry=None,
            )
        )
        return None

    default = spec.get("default")

    if mode == "strict":
        if "default" in spec:
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        f"aggregate_account_metadata: aggregation '{key}' sets "
                        f"'default' but mode is 'strict'; 'default' is only valid "
                        f"when mode is 'default'"
                    ),
                    entry=None,
                )
            )
            return None
        default = None
    else:  # mode == "default"
        if not isinstance(default, (str, bool)) or (
            isinstance(default, str) and not default
        ):
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        f"aggregate_account_metadata: aggregation '{key}' with mode "
                        f"'default' requires a non-empty 'default' string or bool"
                    ),
                    entry=None,
                )
            )
            return None

    return AggregationSpec(
        key=key,
        source=source,
        mode=mode,
        default=default,
        value_map=value_map,
        declared_values=frozenset(value_map),
    )


def _parse_config(
    config: str | None,
) -> tuple[list[AggregationSpec], list[ParserError]]:
    """Parse inline Python-literal config into aggregation specs.

    Accepts Python dict syntax — single or double quotes, string or list
    values. Returns (specs, errors). On any error the caller should return the
    entries unchanged.
    """
    errors: list[ParserError] = []

    if not config:
        return [], errors

    try:
        cfg: Any = ast.literal_eval(config)
    except (ValueError, SyntaxError) as e:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=f"aggregate_account_metadata: Invalid config: {e}",
                entry=None,
            )
        )
        return [], errors

    if not isinstance(cfg, dict):
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    "aggregate_account_metadata: config must be a dict, "
                    f"got {type(cfg).__name__}"
                ),
                entry=None,
            )
        )
        return [], errors

    unknown = set(cfg.keys()) - _ALLOWED_TOP_KEYS
    if unknown:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    f"aggregate_account_metadata: Unknown config keys: "
                    f"{', '.join(sorted(unknown))}. "
                    f"Allowed: {', '.join(sorted(_ALLOWED_TOP_KEYS))}"
                ),
                entry=None,
            )
        )
        return [], errors

    raw_aggs = cfg.get("aggregations")
    if not isinstance(raw_aggs, dict) or not raw_aggs:
        errors.append(
            ParserError(
                source=dict(_CONFIG_SOURCE),
                message=(
                    "aggregate_account_metadata: 'aggregations' must be "
                    "a non-empty dict"
                ),
                entry=None,
            )
        )
        return [], errors

    specs: list[AggregationSpec] = []
    for key, spec in raw_aggs.items():
        parsed = _parse_aggregation(key, spec, errors)
        if parsed is not None:
            specs.append(parsed)

    return specs, errors


def _entry_source(entry: data.Open) -> dict[str, Any]:
    """Build a ParserError source dict from an Open directive's metadata."""
    if entry.meta:
        return {
            "filename": entry.meta.get("filename", "unknown"),
            "lineno": entry.meta.get("lineno", 0),
        }
    return {"filename": "unknown", "lineno": 0}


def aggregate_account_metadata(
    entries: data.Entries,
    options_map: dict,
    config: str | None = None,
) -> tuple[data.Entries, list[ParserError]]:
    """Derive aggregated metadata keys on Open directives.

    Args:
        entries: List of beancount entries
        options_map: Beancount options map
        config: Optional inline Python-literal dict describing aggregations

    Returns:
        Tuple of (modified_entries, errors)
    """
    errors: list[ParserError] = []

    specs, config_errors = _parse_config(config)
    if config_errors:
        errors.extend(config_errors)
        return entries, errors

    if not specs:
        return entries, errors

    observed: dict[str, set[str]] = {spec.key: set() for spec in specs}
    new_entries: list[data.Directive] = []
    derived_count = 0

    for entry in entries:
        if not isinstance(entry, data.Open):
            new_entries.append(entry)
            continue

        meta = entry.meta or {}
        updates: dict[str, Any] = {}

        for spec in specs:
            src_value = meta.get(spec.source)
            if not isinstance(src_value, str):
                continue
            observed[spec.key].add(src_value)

            if src_value in spec.value_map:
                updates[spec.key] = spec.value_map[src_value]
            elif spec.mode == "default":
                updates[spec.key] = spec.default
            else:  # strict
                errors.append(
                    ParserError(
                        source=_entry_source(entry),
                        message=(
                            f"aggregate_account_metadata: source value "
                            f"'{src_value}' for '{spec.source}' is not mapped by "
                            f"aggregation '{spec.key}' (mode 'strict')"
                        ),
                        entry=None,
                    )
                )

        if not updates:
            new_entries.append(entry)
            continue

        new_meta = dict(meta)
        for key, value in updates.items():
            if key in new_meta:
                logger.warning(
                    "aggregate_account_metadata: conflict on account '%s' key '%s' "
                    "— existing value wins",
                    entry.account,
                    key,
                )
            else:
                new_meta[key] = value
                derived_count += 1

        new_entries.append(entry._replace(meta=new_meta))

    for spec in specs:
        unused = sorted(spec.declared_values - observed[spec.key])
        if unused:
            errors.append(
                ParserError(
                    source=dict(_CONFIG_SOURCE),
                    message=(
                        f"aggregate_account_metadata: aggregation '{spec.key}' "
                        f"declares source value(s) never observed on any Open: "
                        f"{', '.join(unused)}"
                    ),
                    entry=None,
                )
            )

    logger.debug(
        "aggregate_account_metadata: derived %d metadata values "
        "across %d aggregation(s)",
        derived_count,
        len(specs),
    )
    return new_entries, errors
