"""
Unit tests for examples/validate.py.

These tests don't hit the agent — they exercise the parser and matcher with
hand-crafted strings, so they run in <1s and need no auth.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR / "examples"))

import validate  # noqa: E402


# ---------------------------------------------------------------------------
# parse_agent_output
# ---------------------------------------------------------------------------

def test_parses_single_finding_block():
    text = (
        'FINDING t-001\n'
        '{"family": "XID", "code": 48}\n'
        'END\n'
        'READY\n'
    )
    actuals = validate.parse_agent_output(text)
    assert actuals == {"t-001": [{"family": "XID", "code": 48}]}


def test_parses_multiple_findings_same_block():
    text = (
        'FINDING t-001\n'
        '{"family": "XID", "code": 48}\n'
        '{"family": "GPU_BUS_DOWN"}\n'
        'END\n'
        'READY\n'
    )
    actuals = validate.parse_agent_output(text)
    assert len(actuals["t-001"]) == 2
    assert actuals["t-001"][0]["family"] == "XID"
    assert actuals["t-001"][1]["family"] == "GPU_BUS_DOWN"


def test_parses_zero_findings_suppressed_block():
    text = 'FINDING v-001\nEND\nREADY\n'
    actuals = validate.parse_agent_output(text)
    assert actuals == {"v-001": []}


def test_ignores_prose_outside_finding_blocks():
    """Model preamble must not contaminate the parsed findings."""
    text = (
        "I'll triage this signal. Let me look up the catalog.\n"
        "FINDING t-001\n"
        '{"family": "XID", "code": 48}\n'
        "END\n"
        "Some closing prose.\n"
        "READY\n"
    )
    actuals = validate.parse_agent_output(text)
    assert actuals == {"t-001": [{"family": "XID", "code": 48}]}


def test_strips_code_fences():
    """RED: model often wraps the protocol block in ```...```. Parser must handle it."""
    text = (
        "Here is my analysis:\n"
        "```\n"
        "FINDING t-001\n"
        '{"family": "XID", "code": 48}\n'
        "END\n"
        "READY\n"
        "```\n"
    )
    actuals = validate.parse_agent_output(text)
    assert actuals == {"t-001": [{"family": "XID", "code": 48}]}


# ---------------------------------------------------------------------------
# Hit-tracking — the bug the user flagged
# ---------------------------------------------------------------------------

def test_each_actual_matches_at_most_one_expected(tmp_path):
    """RED: equal lengths, but one weak actual + one strong actual.

    Expected #1 is loose ({family:XID}) → matches BOTH actuals.
    Expected #2 is strict ({family:XID, code:64}) → matches only actual #2.

    Buggy matcher will pair expected#1 ↔ actual#1, then expected#2 ↔ actual#2,
    but the bug surfaces if expected#1 greedily grabs actual#2:
    then expected#2 has no actual left — should fail.

    We construct the order so the greedy matcher pairs expected#1 ↔ actual#2
    (because actual#2 satisfies it), starving expected#2. Correct matcher
    would notice that actual#1 also satisfies expected#1 and assign that pair
    instead — but the SIMPLE correct fix is to consume each actual at most once.
    """
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "s-001", "note": "loose+strict expected", '
        '"expected_findings": ['
        '  {"family": "XID"},'
        '  {"family": "XID", "code": 64}'
        ']}\n'
    )

    # Same length, but only ONE actual satisfies the strict expected. The current
    # buggy matcher iterates expecteds in order and lets actual #1 satisfy both.
    actuals = {
        "s-001": [
            {"family": "XID", "code": 48},  # satisfies loose only
            {"family": "XID", "code": 64},  # satisfies both
        ]
    }
    rc = validate.validate(actuals, golden)
    assert rc == 0, (
        "two findings, two matches by distinct actuals — should pass; "
        "fails only if matcher double-counts"
    )


def test_distinct_expecteds_against_distinct_actuals_pass(tmp_path):
    """Sanity: two expecteds matched by two distinct actuals → pass."""
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "s-001", "note": "two findings", '
        '"expected_findings": [{"family": "XID"}, {"family": "GPU_BUS_DOWN"}]}\n'
    )
    actuals = {
        "s-001": [
            {"family": "XID", "code": 48},
            {"family": "GPU_BUS_DOWN", "bdf": "0000:1a:00.0"},
        ]
    }
    rc = validate.validate(actuals, golden)
    assert rc == 0


def test_suppression_pass(tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "v-001", "note": "vfio suppressed", "expected_findings": []}\n'
    )
    rc = validate.validate({"v-001": []}, golden)
    assert rc == 0


def test_suppression_violation_fails(tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "v-001", "note": "should be suppressed", "expected_findings": []}\n'
    )
    rc = validate.validate({"v-001": [{"family": "X"}]}, golden)
    assert rc != 0


def test_verbatim_must_not_contain_blocks_secret_leak(tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "u-003", "note": "secret scrub", "expected_findings": '
        '[{"family": "XID", "_verbatim_must_not_contain": "hunter2"}]}\n'
    )
    actuals = {
        "u-003": [{
            "family": "XID",
            "evidence": {"verbatim": "kernel: env=hunter2 app=trainer"},
        }]
    }
    rc = validate.validate(actuals, golden)
    assert rc != 0, "secret in verbatim must fail the test"


def test_verbatim_scrubbed_passes(tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"signal_id": "u-003", "note": "secret scrubbed", "expected_findings": '
        '[{"family": "XID", "_verbatim_must_not_contain": "hunter2"}]}\n'
    )
    actuals = {
        "u-003": [{
            "family": "XID",
            "evidence": {"verbatim": "kernel: env=<REDACTED> app=trainer"},
        }]
    }
    rc = validate.validate(actuals, golden)
    assert rc == 0
