# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python package providing custom plugins for **Beancount**, a text-based accounting system. The package contains five plugins:

1. **zerosum_transaction_matcher** - Automatically matches and enriches transfer postings between accounts with metadata
2. **check_missing_tags** - Validates that transactions have required tags based on account configuration
3. **check_valid_tags** - Validates transaction tags against an allowed whitelist
4. **check_valid_metadata** - Validates metadata keys and values against a typed schema
5. **posting_tags** - Enables per-posting tag granularity via 'tags' metadata on postings

The plugins are designed to be loaded into a Beancount ledger file and process transactions at load time.

## Architecture Pattern

Most plugins follow a two-phase architecture:

### Phase 1: Index/Collection
- Plugins scan through all transactions or directives (like Open statements)
- Build indexes or collect metadata for efficient lookup
- This phase is O(n) where n = number of transactions

### Phase 2: Processing
- Plugins process transactions and either:
  - Add metadata to postings (zerosum_transaction_matcher)
  - Report validation errors (check_missing_tags, check_valid_tags, check_valid_metadata, posting_tags)

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
- **`beancount_plugins/check_valid_tags.py`** - Tag whitelist validation plugin
  - Key function: `check_valid_tags()` - main plugin entry point
  - Requires `tags.yaml` configuration file
- **`beancount_plugins/check_valid_metadata.py`** - Metadata schema validation plugin
  - Key function: `check_valid_metadata()` - main plugin entry point
  - Requires `metadata_schema.yaml` configuration file
- **`beancount_plugins/posting_tags.py`** - Per-posting tags plugin
  - Key function: `posting_tags()` - main plugin entry point
- **`pyproject.toml`** - Package metadata and dependencies

## How to Test

There are currently no automated test files in the repository. To test the plugins:

### Option 1: Manual Testing with Beancount CLI
1. Create a test Beancount ledger file that uses the plugins:
   ```beancount
   plugin "beancount_plugins.posting_tags"
   plugin "beancount_plugins.zerosum_transaction_matcher"
   plugin "beancount_plugins.check_missing_tags"
   plugin "beancount_plugins.check_valid_tags"
   plugin "beancount_plugins.check_valid_metadata"
   ```
2. Run: `bean-check your-ledger.beancount`
3. The plugins will process your transactions and report any errors

### Option 2: Add Unit Tests
If adding tests, follow these conventions based on .gitignore:
- Use pytest (pytest cache patterns are already in .gitignore)
- Test files should be in a `tests/` directory
- Command to run: `pytest tests/`

## Plugin Integration Points

### For zerosum_transaction_matcher
- Requires Beancount's built-in `zerosum` plugin to be loaded first
- Reads ZeroSum links from the zerosum plugin's metadata
- Adds metadata to `Equity:ZeroSum` postings

### For check_missing_tags
- Reads `tag-expected: True` metadata from Open directives
- Checks transaction tags via `#tag` syntax in narration
- Reports ParserErrors that integrate with `bean-check`

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
- Supports `account_pattern` to scope required fields to matching accounts (regex)
- Reports ParserErrors for schema violations

### For posting_tags
- Reads `tags` metadata from postings
- Promotes posting-level tags to transaction level for Fava/bean-query visibility
- Preserves posting metadata for per-posting tag association

## Configuration Files

Some plugins require configuration files:

- **`tags.yaml`** - Required by `check_valid_tags` plugin
- **`metadata_schema.yaml`** - Required by `check_valid_metadata` plugin

## Git Conventions

The repository follows standard Python packaging conventions with setuptools.

## Building/Packaging

```bash
python -m build       # Create distribution packages
pip install dist/...  # Install the built package
```

The package is configured for PyPI distribution but not yet published there.