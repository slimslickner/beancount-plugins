# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python package providing custom plugins for **Beancount**, a text-based accounting system. The package contains two plugins:

1. **zerosum_transaction_matcher** - Automatically matches and enriches transfer postings between accounts with metadata
2. **check_missing_tags** - Validates that transactions have required tags based on account configuration

The plugins are designed to be loaded into a Beancount ledger file and process transactions at load time.

## Architecture Pattern

Both plugins follow the same two-phase architecture:

### Phase 1: Index/Collection
- Plugins scan through all transactions or directives (like Open statements)
- Build indexes or collect metadata for efficient lookup
- This phase is O(n) where n = number of transactions

### Phase 2: Processing
- Plugins process transactions and either:
  - Add metadata to postings (zerosum_transaction_matcher)
  - Report validation errors (check_missing_tags)

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
- **`beancount_plugins/zerosum_transaction_matcher.py`** - Transfer matching plugin (~17KB)
  - Key function: `process_entry()` - main plugin entry point
  - Uses ZeroSum links created by Beancount's built-in zerosum plugin
- **`beancount_plugins/check_missing_tags.py`** - Tag validation plugin (~5KB)
  - Key function: `process_entry()` - main plugin entry point
  - Scans Open directives for `tag-expected: True` metadata
- **`pyproject.toml`** - Package metadata and dependencies

## How to Test

There are currently no automated test files in the repository. To test the plugins:

### Option 1: Manual Testing with Beancount CLI
1. Create a test Beancount ledger file that uses the plugins:
   ```beancount
   plugin "beancount_plugins.zerosum_transaction_matcher"
   plugin "beancount_plugins.check_missing_tags"
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

## Git Conventions

The repository follows standard Python packaging conventions with setuptools. Recent commits (like `159fecf fix the transaction matcher`) suggest fixes and refinements to the matching logic.

## Building/Packaging

```bash
python -m build       # Create distribution packages
pip install dist/...  # Install the built package
```

The package is configured for PyPI distribution but not yet published there.
