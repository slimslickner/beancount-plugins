# Design: promote_account_metadata Plugin

**Date:** 2026-07-03

## Summary

New Beancount plugin that reads metadata from `Open` directives and promotes those key-value pairs onto any posting that uses that account.

## Problem

Users annotate accounts with semantic metadata (e.g. `tax-treatment: "pre-tax"`) on `Open` directives. Currently that metadata is invisible to transactions — there is no way to automatically inherit it at the posting level for use in queries or downstream plugins.

## Approach

Inline JSON config string in the plugin declaration (Option A). Consistent with the simpler plugins in this codebase. Parsed with `json.loads`.

## Architecture

Two-phase pattern matching all other plugins in this codebase:

**Phase 1 — Index:**
Scan `Open` directives. For each, collect metadata (excluding system keys `filename`/`lineno`). Apply whitelist/blacklist filter. Store as `dict[account_name, dict[key, value]]`.

**Phase 2 — Promote:**
Walk all `Transaction` entries. For each posting, look up account in index. Merge promotable metadata onto the posting — existing posting values win on conflict.

Config is parsed once before Phase 1.

## Config

Passed as JSON string in the plugin declaration:

```
plugin "beancount_plugins.promote_account_metadata"
plugin "beancount_plugins.promote_account_metadata" "{\"whitelist\": [\"tax-treatment\"]}"
plugin "beancount_plugins.promote_account_metadata" "{\"blacklist\": [\"internal-note\"]}"
plugin "beancount_plugins.promote_account_metadata" "{\"whitelist\": [\"tax-treatment\"], \"blacklist\": [\"x\"]}"
```

**Filter rules:**
- No config → promote all metadata keys
- `whitelist` only → promote only listed keys
- `blacklist` only → promote all keys except listed
- Both → whitelist wins (blacklist ignored)

**No built-in exclusions.** User is fully responsible for filtering plugin-control keys like `tag-expected` if needed.

## Error Handling

**ParserErrors (returned, shown by bean-check):**
- Invalid JSON config string
- Unrecognized keys in config JSON (not `whitelist` or `blacklist`)

**Warnings (logging.warning, visible with bean-check -v):**
- Conflict: posting already has a key that would be promoted → log account name, key, and transaction narration; posting value wins

## Files

- `beancount_plugins/promote_account_metadata.py` — plugin implementation + full docstring docs
- No separate README; docs live in the module docstring

## Tests

Additions to `tests/sample.beancount` and `tests/test_plugins.py`:

- Metadata promoted to matching posting
- Metadata NOT promoted to non-matching posting
- Existing posting key wins on conflict; warning logged
- Whitelist: only listed keys promoted
- Blacklist: listed keys excluded
- Both whitelist+blacklist: whitelist wins, blacklist ignored
- No config: all keys promoted
