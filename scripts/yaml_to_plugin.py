#!/usr/bin/env python3
"""Convert a YAML config file into a Beancount ``plugin`` directive.

The inline-config plugins in this package accept a Python-dict literal as the
second argument to ``plugin ...``. This tool reads a YAML file (e.g.
``tags.yaml`` or ``metadata_schema.yaml``) and emits the equivalent directive,
so a file-based config can be pasted inline into a ledger.

The YAML is loaded with ``yaml.safe_load`` and re-serialized as a Python literal
(``True``/``False``, single-quoted strings) that the plugins can parse with
``ast.literal_eval``. Output is fully expanded: every mapping and list is
rendered with one entry per indented line, recursively.

USAGE:
    python scripts/yaml_to_plugin.py tags.yaml
    python scripts/yaml_to_plugin.py tags.yaml --plugin beancount_plugins.check_valid_tags
    python scripts/yaml_to_plugin.py metadata_schema.yaml --out directive.txt

The plugin module is inferred from the filename when possible
(``tags.yaml`` -> ``beancount_plugins.check_valid_tags``,
``metadata_schema.yaml`` -> ``beancount_plugins.check_valid_metadata``);
otherwise pass ``--plugin``.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path
from typing import Any

import yaml

# Filename -> plugin module, used when --plugin is not supplied.
_MODULE_BY_FILENAME: dict[str, str] = {
    "tags.yaml": "beancount_plugins.check_valid_tags",
    "tags.yml": "beancount_plugins.check_valid_tags",
    "metadata_schema.yaml": "beancount_plugins.check_valid_metadata",
    "metadata_schema.yml": "beancount_plugins.check_valid_metadata",
}

_INDENT = "  "


def _normalize(value: Any) -> Any:
    """Convert YAML-only scalars into forms that are valid Python literals.

    ``datetime.date``/``datetime.datetime`` values are rendered as ISO strings;
    everything else is returned unchanged.
    """
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _to_literal(value: Any, level: int = 0) -> str:
    """Render a value as an indented Python literal.

    Every non-empty mapping and list is broken across multiple indented lines,
    one entry per line, recursively, so no two keys ever share a line. Empty
    containers render inline as ``{}`` / ``[]``.
    """
    indent = _INDENT * level
    child_indent = _INDENT * (level + 1)

    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for key, item in value.items():
            lines.append(
                f"{child_indent}{_to_literal(key)}: {_to_literal(item, level + 1)},"
            )
        lines.append(f"{indent}}}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        for item in value:
            lines.append(f"{child_indent}{_to_literal(item, level + 1)},")
        lines.append(f"{indent}]")
        return "\n".join(lines)

    return repr(value)


def _escape_for_beancount(text: str) -> str:
    """Escape a literal so it can be embedded in a Beancount double-quoted string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def infer_module(path: Path) -> str | None:
    """Infer the plugin module from the config filename, if known."""
    return _MODULE_BY_FILENAME.get(path.name.lower())


def convert(yaml_path: Path, plugin: str) -> str:
    """Load a YAML file and return the equivalent Beancount plugin directive."""
    with open(yaml_path, encoding="utf-8") as f:
        loaded = yaml.safe_load(f)

    if not isinstance(loaded, dict):
        raise TypeError(
            f"{yaml_path}: expected a YAML mapping at the top level, "
            f"got {type(loaded).__name__}"
        )

    literal = _to_literal(_normalize(loaded))
    return f'plugin "{plugin}" "{_escape_for_beancount(literal)}"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a YAML config file into a Beancount plugin directive.",
    )
    parser.add_argument("yaml_file", type=Path, help="YAML config file to convert")
    parser.add_argument(
        "--plugin",
        help="Beancount plugin module to reference (overrides filename inference)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the directive to this file instead of stdout",
    )
    args = parser.parse_args(argv)

    plugin = args.plugin or infer_module(args.yaml_file)
    if not plugin:
        parser.error(
            "could not infer the plugin module from the filename; pass --plugin"
        )

    try:
        directive = convert(args.yaml_file, plugin)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    output = directive + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
