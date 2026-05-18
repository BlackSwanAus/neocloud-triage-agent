"""
Targeted RED: prove the double-counting bug.

Two expecteds, both loose ({family:XID}); only ONE actual. The buggy validator
short-circuits on length mismatch (2 expected vs 1 actual) and reports failure
— but for the WRONG reason. We need a test that fails ONLY because of the bug.

Construction:
  - 2 expecteds, 2 actuals (equal length, no short-circuit).
  - Expected #1 = {family: XID}            (loose)
  - Expected #2 = {family: XID, code: 999} (no actual satisfies)
  - Actual  #1 = {family: XID, code: 48}
  - Actual  #2 = {family: XID, code: 64}

Correct validator: expected#1 matches actual#1 OR #2, expected#2 matches nothing
  → FAIL (one unmatched expected).

Buggy validator (current): both expecteds iterate over ALL actuals; expected#1
  matches actual#1, expected#2 matches NOTHING. → also FAIL.

Both happen to fail. Need a different shape to surface the bug:

  - Expected #1 = {family: XID}              (matches both actuals)
  - Expected #2 = {family: XID}              (matches both actuals)
  - Actual  #1 = {family: XID, code: 48}
  - Actual  #2 = {family: XID, code: 64}

  Correct validator: pair expected#1↔actual#1, expected#2↔actual#2 → PASS
  Buggy validator (this is what we need to expose):
    actually still PASSES because both expecteds find a match (same actual).
    The bug only matters when distinct identity matters — e.g., when one actual
    is missing.

Real surfacing: 2 expecteds, but only 1 actual. Length mismatch trips first
  — bug is hidden. To bypass the length check, pad actuals with a no-match item:

  - Expected #1 = {family: XID}
  - Expected #2 = {family: GPU_BUS_DOWN}
  - Actual  #1 = {family: XID, code: 48}
  - Actual  #2 = {family: XID, code: 64}   # padding, won't match expected#2

  Correct: expected#1↔actual#1, expected#2↔NOTHING → FAIL
  Buggy:   expected#1 matches some XID actual, expected#2 matches NOTHING → FAIL

  Both fail. Bug-vs-correct can't be distinguished here either.

Real surfacing requires that the bug CHANGES the verdict. Construction:
  - Expected #1 = {family: XID, code: 48}
  - Expected #2 = {family: XID}              (loose — any XID matches)
  - Actual  #1 = {family: XID, code: 48}
  - Actual  #2 = {family: XID, code: 48}     (DUPLICATE!)

  Correct (consume-once): expected#1 ↔ actual#1, expected#2 ↔ actual#2 → PASS
  Buggy (no consume):     expected#1 ↔ actual#1, expected#2 ↔ actual#1 → also PASS

  Still can't distinguish. The bug as I described it does NOT change verdict
  given length-equal lists. It only changes verdict when length-equal AND one
  actual is unique-required by one expected — i.e., the validator over-claims
  matches. We need an actual that is required by expected#1 but the buggy
  matcher steals it for expected#2.

Final construction:
  - Expected #1 = {family: XID, code: 48}     (strict — only actual#1 matches)
  - Expected #2 = {family: XID, code: 48}     (strict — only actual#1 matches)
  - Actual  #1 = {family: XID, code: 48}
  - Actual  #2 = {family: XID, code: 999}     (no match for either expected)

  Correct: 2 distinct expecteds need 2 distinct actuals → only 1 actual
    available → FAIL.
  Buggy:   expected#1 ↔ actual#1, expected#2 ↔ actual#1 (reuses!) → PASS.

  Verdicts DIFFER. This test will RED on the current code (passes when it
  shouldn't) and GREEN after we add hit-tracking.
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
