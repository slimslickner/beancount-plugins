"""Tests for scripts/materialize_pads.py."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PAD_DIRECTIVE_RE = r"^\d{4}-\d{2}-\d{2} pad "

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "materialize_pads.py"

MAIN = """\
option "operating_currency" "USD"
include "accounts.beancount"
include "pads.beancount"
"""

ACCOUNTS = """\
2013-04-01 open Assets:Checking
2013-04-01 open Equity:Opening-Balances
"""


def _write_ledger(tmp_path: Path, pads: str) -> Path:
    (tmp_path / "accounts.beancount").write_text(ACCOUNTS, encoding="utf-8")
    (tmp_path / "pads.beancount").write_text(pads, encoding="utf-8")
    main = tmp_path / "main.beancount"
    main.write_text(MAIN, encoding="utf-8")
    return main


def _run(main: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(main), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


PAD_WITH_BALANCE = """\
2013-04-01 pad Assets:Checking Equity:Opening-Balances

2013-05-01 balance Assets:Checking 172.45 USD
"""


def test_materializes_pad_in_included_file(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    result = _run(main)

    assert result.returncode == 0, result.stderr
    pads = (tmp_path / "pads.beancount").read_text(encoding="utf-8")
    assert not re.search(PAD_DIRECTIVE_RE, pads, re.MULTILINE)
    assert (
        '2013-04-01 * "Materialized pad for Assets:Checking from Equity:Opening-Balances"'
        in pads
    )
    assert "Assets:Checking           172.45 USD" in pads
    assert "Equity:Opening-Balances  -172.45 USD" in pads
    # No marker metadata is emitted.
    assert "pad-source" not in pads
    # The balance assertion is left in place and still passes.
    assert "2013-05-01 balance Assets:Checking 172.45 USD" in pads


def test_does_not_touch_other_files(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    accounts_before = (tmp_path / "accounts.beancount").read_text(encoding="utf-8")
    _run(main)
    assert (tmp_path / "accounts.beancount").read_text(
        encoding="utf-8"
    ) == accounts_before


def test_materialized_ledger_loads_cleanly(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    _run(main)

    from beancount import loader
    from beancount.core import data, flags

    entries, errors, _ = loader.load_file(str(main))
    assert not [e for e in errors if "balance" in e.message.lower()]
    padding = [
        e
        for e in entries
        if isinstance(e, data.Transaction) and e.flag == flags.FLAG_PADDING
    ]
    assert padding == []


def test_dry_run_writes_nothing(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    before = (tmp_path / "pads.beancount").read_text(encoding="utf-8")

    result = _run(main, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "pads.beancount").read_text(encoding="utf-8") == before
    assert "dry-run" in result.stderr
    assert "-2013-04-01 pad Assets:Checking Equity:Opening-Balances" in result.stdout
    assert "+2013-04-01 *" in result.stdout


def test_idempotent_second_run(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    _run(main)
    after_first = (tmp_path / "pads.beancount").read_text(encoding="utf-8")

    result = _run(main)

    assert result.returncode == 1
    assert "no pads to materialize" in result.stderr
    assert (tmp_path / "pads.beancount").read_text(encoding="utf-8") == after_first


def test_custom_narration(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    result = _run(main, "--narration", "Opening {source_account} {amount} {currency}")
    assert result.returncode == 0, result.stderr
    pads = (tmp_path / "pads.beancount").read_text(encoding="utf-8")
    assert '"Opening Equity:Opening-Balances 172.45 USD"' in pads


def test_pad_metadata_span_is_consumed(tmp_path):
    pads_text = (
        "2013-04-01 pad Assets:Checking Equity:Opening-Balances\n"
        '  note: "opening balance"\n'
        "\n"
        "2013-05-01 balance Assets:Checking 172.45 USD\n"
    )
    main = _write_ledger(tmp_path, pads_text)
    result = _run(main)
    assert result.returncode == 0, result.stderr

    pads = (tmp_path / "pads.beancount").read_text(encoding="utf-8")
    assert "note:" not in pads
    assert not re.search(PAD_DIRECTIVE_RE, pads, re.MULTILINE)
    assert (
        '2013-04-01 * "Materialized pad for Assets:Checking from Equity:Opening-Balances"'
        in pads
    )


def test_unused_pad_is_reported(tmp_path):
    pads_text = (
        "2013-04-01 pad Assets:Checking Equity:Opening-Balances\n"
        "\n"
        "2013-05-01 balance Assets:Checking 0.00 USD\n"
    )
    main = _write_ledger(tmp_path, pads_text)
    before = (tmp_path / "pads.beancount").read_text(encoding="utf-8")

    result = _run(main)

    assert result.returncode == 1
    assert "unused pad" in result.stderr
    assert (tmp_path / "pads.beancount").read_text(encoding="utf-8") == before


def test_missing_ledger_reports_error(tmp_path):
    result = _run(tmp_path / "does-not-exist.beancount")
    assert result.returncode == 1
    assert "no such file" in result.stderr


def test_invalid_narration_template(tmp_path):
    main = _write_ledger(tmp_path, PAD_WITH_BALANCE)
    result = _run(main, "--narration", "oops {nope}")
    assert result.returncode == 1
    assert "invalid --narration template" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
