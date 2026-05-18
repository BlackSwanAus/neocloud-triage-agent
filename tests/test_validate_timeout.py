"""
RED: validate.py must not hang forever if runner.py hangs.

We can't easily hang the real runner without hitting the live model, so we
test the timeout primitive directly via a tiny fake runner that sleeps.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR / "examples"))

import validate  # noqa: E402


def test_run_agent_respects_timeout(tmp_path, monkeypatch):
    """A hanging fake runner must be killed by the timeout, not block forever."""
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(textwrap.dedent("""
        import sys, time
        # Read input but never produce output — simulate model hang.
        sys.stdin.read()
        time.sleep(60)
    """))
    monkeypatch.setattr(validate, "RUNNER", fake_runner)

    feed = tmp_path / "feed.txt"
    feed.write_text("SIGNAL t-001\nfoo\nEND\nSHUTDOWN\n")

    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        validate.run_agent(feed, timeout=1.5)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"timeout did not kill quickly: {elapsed:.2f}s"


def test_run_agent_returns_output_under_timeout(tmp_path, monkeypatch):
    """A fast fake runner must complete and return its stdout."""
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(textwrap.dedent("""
        import sys
        sys.stdin.read()
        sys.stdout.write('FINDING t-001\\n{"family":"XID"}\\nEND\\nREADY\\n')
    """))
    monkeypatch.setattr(validate, "RUNNER", fake_runner)

    feed = tmp_path / "feed.txt"
    feed.write_text("SIGNAL t-001\nfoo\nEND\nSHUTDOWN\n")

    out = validate.run_agent(feed, timeout=5)
    assert "FINDING t-001" in out
    assert '"family":"XID"' in out
