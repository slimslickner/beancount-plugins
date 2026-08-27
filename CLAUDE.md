# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python package providing custom plugins for **Beancount**, a text-based accounting system. The package contains ten plugins:

1. **zerosum_transaction_matcher** - Automatically matches and enriches transfer postings between accounts with metadata
2. **check_missing_tags** - Validates that transactions have required tags based on account configuration
3. **check_missing_links** - Validates that transactions posting to link-required accounts include at least one link (via `link-expected: True` on Open directives)
4. **check_valid_tags** - Validates transaction tags against an allowed whitelist
5. **check_valid_metadata** - Validates metadata keys and values against a typed schema
6. **posting_tags** - Enables per-posting tag granularity via 'tags' metadata on postings
7. **transfer_remove_payee** - Errors on transfer-shaped transactions (Assets/Liabilities/Equity only) that incorrectly carry a payee — excludes `Assets:Receivable:` and same-parent transfers
8. **missing_contribution_year** - Errors on retirement contributions whose receiving posting lacks a `contribution-year` metadata key; requires a "destination + counterparty" pair to qualify so random asset movements don't trip it
9. **promote_account_metadata** - Copies metadata from each account's Open directive onto postings for that account (supports `whitelist` / `blacklist` config; load *before* `check_valid_metadata` if you want promoted keys validated)
10. **implicit_prices_flagged** - Drop-in replacement for Beancount's built-in `implicit_prices` that honors a per-posting `no-implicit-price: TRUE` opt-out for cost-derived prices (e.g. in-kind transfers)

The plugins are designed to be loaded into a Beancount ledger file and process transactions at load time.

## Architecture Pattern

Most plugins follow a two-phase architecture:

### Phase 1: Index/Collection
- Plugins scan through all transactions or directives (like Open statements)
- Build indexes or collect metadata for efficient lookup
- This phase is O(n) where n = number of transactions

### Phase 2: Processing
- Plugins process transactions and either:
  - Add metadata to postings (`zerosum_transaction_matcher`, `promote_account_metadata`, `posting_tags`)
  - Synthesize new entries (`implicit_prices_flagged` injects `Price` directives)
  - Report validation errors as `ParserError`s (`check_missing_tags`, `check_missing_links`, `check_valid_tags`, `check_valid_metadata`, `transfer_remove_payee`, `missing_contribution_year`)

**Key Insight**: This pattern allows plugins to operate efficiently without nested lookups.

## Development Setup

### Install Dependencies
```bash
pip install -e .  # Install in development mode with local dependencies
```

### Python Version
The project requires **Python 3.13+** (see `.python-version`).

## Code Quality Checks

**Every time you make changes to Python files, you MUST run all of these checks and ensure they resolve with zero errors:**

```bash
uv run ruff check --fix  # Fix linting issues automatically
uv run ruff format       # Format code
uv run ty check          # Type checking
```

All three commands must complete with zero errors before committing changes. If any errors remain after running `ruff check --fix` and `ruff format`, you must fix them manually. Type errors from `ty check` must be resolved by adding appropriate type annotations.

## Important Files

- **`beancount_plugins/__init__.py`** - Package entry point with plugin documentation
- **`beancount_plugins/zerosum_transaction_matcher.py`** - Transfer matching plugin
  - Key function: `zerosum_transaction_matcher()` - main plugin entry point
  - Uses ZeroSum links created by Beancount's built-in zerosum plugin
- **`beancount_plugins/check_missing_tags.py`** - Tag validation plugin
  - Key function: `check_missing_tags()` - main plugin entry point
  - Scans Open directives for `tag-expected: True` metadata
- **`beancount_plugins/check_missing_links.py`** - Link validation plugin
  - Key function: `check_missing_links()` - main plugin entry point
  - Scans Open directives for `link-expected: True` metadata
  - Sibling of `check_missing_tags`; same shape, different key
- **`beancount_plugins/check_valid_tags.py`** - Tag whitelist validation plugin
  - Key function: `check_valid_tags()` - main plugin entry point
  - Requires `tags.yaml` configuration file
- **`beancount_plugins/check_valid_metadata.py`** - Metadata schema validation plugin
  - Key function: `check_valid_metadata()` - main plugin entry point
  - Requires `metadata_schema.yaml` configuration file
- **`beancount_plugins/posting_tags.py`** - Per-posting tags plugin
  - Key function: `posting_tags()` - main plugin entry point
- **`beancount_plugins/transfer_remove_payee.py`** - Transfer-payee guard plugin
  - Key function: `transfer_remove_payee()` - main plugin entry point
  - No config required
- **`beancount_plugins/missing_contribution_year.py`** - Contribution-year guard plugin
  - Key function: `missing_contribution_year()` - main plugin entry point
  - Optional inline dict config (parsed via `ast.literal_eval`); defaults: `destination_patterns = ('HSA', '401k', 'IRA', 'DC')` plus seven known contribution-source accounts as counterparties. When `destination_accounts` is explicitly set (non-empty), default patterns are replaced.
  - Load-time account validation: explicitly-configured accounts are checked against Open directives to catch typos
- **`beancount_plugins/promote_account_metadata.py`** - Open-metadata promotion plugin
  - Key function: `promote_account_metadata()` - main plugin entry point
  - Optional inline dict config with `whitelist` / `blacklist` keys (whitelist wins if both provided)
  - System keys (`filename`, `lineno`) are never promoted
- **`beancount_plugins/implicit_prices_flagged.py`** - `implicit_prices` replacement
  - Key function: `add_implicit_prices_flagged()` - main plugin entry point
  - Honors per-posting `no-implicit-price: TRUE` metadata to skip cost-derived price synthesis
  - **Use instead of, not alongside, `beancount.plugins.implicit_prices`**
- **`pyproject.toml`** - Package metadata and dependencies (Python 3.13+, Beancount ≥ 3.2.0)

## How to Test

Tests are in the `tests/` directory and use pytest. Most plugins share `tests/test_plugins.py`; three plugins have dedicated test files because their surface area is larger or independent of the shared fixtures:

- `tests/test_plugins.py` — `posting_tags`, `check_missing_tags`, `check_missing_links`, `check_valid_tags`, `check_valid_metadata`, `transfer_remove_payee`, `promote_account_metadata`, `missing_contribution_year`
- `tests/test_implicit_prices_flagged.py` — `implicit_prices_flagged` only
- `tests/test_missing_contribution_year.py` — deep coverage of `missing_contribution_year` config parsing, exact-match vs regex, account validation, performance
- `tests/test_promote_account_metadata.py` — config parsing, whitelist/blacklist, conflict resolution

Shared fixtures: `tests/sample.beancount` (sample ledger), `tests/metadata_schema.yaml`, `tests/tags.yaml`.

```bash
pytest tests/
```

## Plugin Integration Points

### For zerosum_transaction_matcher
- Requires Beancount's built-in `zerosum` plugin to be loaded first
- Reads ZeroSum links from the zerosum plugin's metadata
- Adds metadata to `Equity:ZeroSum` postings

### For check_missing_tags
- Reads `tag-expected: True` metadata from Open directives
- Checks transaction tags via `#tag` syntax in narration
- Reports ParserErrors that integrate with `bean-check`

### For check_missing_links
- Reads `link-expected: True` metadata from Open directives
- Checks that transactions carry at least one link (via `^link-name` syntax)
- Reports ParserErrors per offending posting with file/line info
- Sibling of `check_missing_tags`; identical shape, different metadata key

### For check_valid_tags
- Reads allowed tags from `tags.yaml` configuration file
- Validates all transaction tags against whitelist
- Supports `require_link` per tag (transactions with that tag must have a link)
- Reports ParserErrors for undefined tags and missing links

### For check_valid_metadata
- Reads metadata schema from `metadata_schema.yaml` configuration file
- Validates metadata keys and values against typed schema
- Supports type constraints (string, int, bool, date, Decimal)
- Supports required fields and allowed_values constraints
- Supports `account_pattern` to scope required fields to matching accounts (regex, matched from the start of the account name)
- Reports ParserErrors for schema violations

### For posting_tags
- Reads `tags` metadata from postings
- Promotes posting-level tags to transaction level for Fava/bean-query visibility
- Preserves posting metadata for per-posting tag association
- Reports ParserErrors for invalid `tags` metadata values (non-list, etc.)

### For transfer_remove_payee
- No config required; emits ParserErrors per offending transaction
- Only flags transactions where *every* posting is on `Assets:`, `Liabilities:`, or `Equity:` accounts (the "transfer-shaped" set)
- Excludes any transaction that touches `Assets:Receivable:` (AR legitimately uses payees)
- Skips transfers where all postings share the same immediate parent (e.g. `Assets:Checking` <-> `Assets:Savings` — narration is sufficient)
- If combined with `check_valid_tags`, add `'transfer-remove-payee'` to `tags.yaml`

### For missing_contribution_year
- Optional inline Python-dict config: `destination_accounts` (exact match, O(1)), `destination_patterns` (regex, applied via `re.search`), `counterparty_accounts` (exact match)
- Default `destination_patterns = ('HSA', '401k', 'IRA', 'DC')` and a hardcoded set of seven counterparty accounts (joint checking/cash-mgmt accounts plus `Income:*:Employer-Contribution` for two employers)
- When `destination_accounts` is explicitly set (non-empty), the default patterns are replaced (no silent regex fallback)
- A transaction only qualifies when it has BOTH a destination posting AND a sibling posting on a counterparty account — random asset movements don't count
- The `contribution-year` key must live on the *receiving* posting (not the transaction), so multi-destination contributions can be tracked per-destination
- Load-time account validation: explicitly-configured accounts are checked against Open directives (typos in config produce ParserErrors instead of silently failing to flag)
- Best loaded AFTER `zerosum_transaction_matcher` so ZeroSum-matched transfers are picked up as counterparties

### For promote_account_metadata
- Optional inline Python-dict config: `whitelist` (only promote these keys) or `blacklist` (promote all except these). Whitelist wins if both provided
- System keys (`filename`, `lineno`) are never promoted
- On key conflicts between Open metadata and existing posting metadata, the posting value wins and a WARNING is logged (visible with `bean-check -v`)
- Load *before* `check_valid_metadata` if you want promoted keys validated against the schema; otherwise add the promoted keys to the posting section of `metadata_schema.yaml`

### For implicit_prices_flagged
- Drop-in replacement for `beancount.plugins.implicit_prices` — use INSTEAD of, not alongside
- Honors per-posting `no-implicit-price: TRUE` metadata to skip cost-derived price synthesis (e.g. in-kind transfers whose cost basis is not today's market price)
- Injects synthesized `Price` entries tagged with `__implicit_prices__: from_price` or `from_cost`

## Configuration Files

Some plugins require configuration files:

- **`tags.yaml`** - Required by `check_valid_tags` plugin
- **`metadata_schema.yaml`** - Required by `check_valid_metadata` plugin

Other plugins accept an optional inline Python-dict literal as a second argument to `plugin ...`, parsed via `ast.literal_eval` (single or double quotes, string or list values):

- **`promote_account_metadata`** — `{'whitelist': 'tax-treatment'}` or `{'blacklist': ['tag-expected', 'link-expected']}`
- **`missing_contribution_year`** — `{'destination_accounts': [...], 'destination_patterns': [...], 'counterparty_accounts': [...]}`

## Git Conventions

The repository follows standard Python packaging conventions with setuptools.

## Building/Packaging

```bash
python -m build       # Create distribution packages
pip install dist/...  # Install the built package
```

The package is configured for PyPI distribution but not yet published there.