"""
Regression: each actual finding can satisfy at most one expected.

Two strict-identical expecteds require two distinct matching actuals. If the
matcher lets the same actual satisfy both, this passes — and that is the bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR / "examples"))

import validate  # noqa: E402


def test_strict_duplicates_require_distinct_actuals(tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "d-001", "note": "two strict expecteds, only one match available", '
        '"expected_findings": ['
        '  {"family": "XID", "code": 48},'
        '  {"family": "XID", "code": 48}'
        ']}\n'
    )
    actuals = {
        "d-001": [
            {"family": "XID", "code": 48},
            {"family": "XID", "code": 999},
        ]
    }
    rc = validate.validate(actuals, golden)
    assert rc != 0, (
        "expected to FAIL: two strict identical expecteds need two distinct "
        "actuals, but only one actual qualifies"
    )
