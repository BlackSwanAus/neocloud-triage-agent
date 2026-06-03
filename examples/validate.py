#!/usr/bin/env python3
"""
Validate runner output against the synthetic golden.

Pipes the synthetic feed into runner.py, parses FINDING blocks, then diffs against
expected.synthetic.jsonl. Reports per-signal pass/fail with explanations.

Usage:
  python validate.py                                  # uses feed.synthetic.txt + expected.synthetic.jsonl
  python validate.py --feed FEED --golden GOLDEN
  python validate.py --offline RUNNER_OUTPUT.txt     # skip live agent, diff a captured output
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
RUNNER = AGENT_DIR / "runner.py"

# Match the agent's FINDING <id> ... END output protocol.
FINDING_HEADER = re.compile(r"^FINDING\s+(\S+)\s*$")


def parse_agent_output(text: str) -> dict[str, list[dict]]:
    """Parse `FINDING <id>\\n{json}\\n...\\nEND` blocks into {sig_id: [findings]}."""
    out: dict[str, list[dict]] = {}
    cur_id: str = ""
    for raw in text.splitlines():
        line = raw.strip()
        m = FINDING_HEADER.match(line)
        if m:
            cur_id = m.group(1)
            out.setdefault(cur_id, [])
            continue
        if line == "END":
            cur_id = ""
            continue
        if line in ("READY", "") or not cur_id:
            continue
        try:
            out[cur_id].append(json.loads(line))
        except json.JSONDecodeError:
            sys.stderr.write(
                f"[validate] non-JSON line under FINDING {cur_id}: {line!r}\n"
            )
    return out


def run_agent(feed: Path, timeout: float = 120.0) -> str:
    """Feed `feed` into runner.py over a stdin pipe, capture stdout.

    Uses input= (a real pipe) rather than a regular-file stdin: runner.py reads
    its feed via asyncio.connect_read_pipe, which rejects regular files
    ("Pipe transport is for pipes/sockets only"). Raises TimeoutExpired on hang.
    """
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        input=feed.read_text(),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"[validate] runner exited {proc.returncode}\n")
        sys.stderr.write(proc.stderr)
    return proc.stdout


def match_finding(actual: dict, expected: dict) -> tuple[bool, str]:
    """Expected fields must be present and equal. `_verbatim_must_not_contain` is special."""
    forbidden = expected.pop("_verbatim_must_not_contain", None)
    for key, want in expected.items():
        got = actual.get(key)
        if got != want:
            return False, f"  field {key!r}: expected {want!r}, got {got!r}"
    if forbidden is not None:
        verbatim = (actual.get("evidence") or {}).get("verbatim", "")
        if forbidden in verbatim:
            return False, f"  verbatim contains forbidden secret: {forbidden!r}"
    return True, ""


def validate(actuals: dict[str, list[dict]], golden_path: Path) -> int:
    pass_n = fail_n = 0
    with golden_path.open() as f:
        for raw in f:
            record = json.loads(raw)
            sig_id = record["signal_id"]
            expected_list = record["expected_findings"]
            note = record["note"]
            got_list = actuals.get(sig_id, [])

            if len(expected_list) == 0:
                if len(got_list) == 0:
                    print(f"PASS {sig_id}  (suppressed)  — {note}")
                    pass_n += 1
                else:
                    print(f"FAIL {sig_id}  expected suppression, got {len(got_list)} finding(s) — {note}")
                    for g in got_list:
                        print(f"    + {json.dumps(g)}")
                    fail_n += 1
                continue

            if len(got_list) != len(expected_list):
                print(
                    f"FAIL {sig_id}  expected {len(expected_list)} finding(s), "
                    f"got {len(got_list)} — {note}"
                )
                fail_n += 1
                continue

            # Hit-tracking: each actual can satisfy at most one expected.
            consumed: set[int] = set()
            all_match = True
            details: list[str] = []
            for want in expected_list:
                matched_idx: int | None = None
                for idx, actual in enumerate(got_list):
                    if idx in consumed:
                        continue
                    ok, _ = match_finding(dict(actual), dict(want))
                    if ok:
                        matched_idx = idx
                        break
                if matched_idx is None:
                    all_match = False
                    # Provide best-effort diagnostic against the first unconsumed.
                    diag_idx = next(
                        (i for i in range(len(got_list)) if i not in consumed),
                        None,
                    )
                    if diag_idx is not None:
                        _, why = match_finding(dict(got_list[diag_idx]), dict(want))
                        details.append(why or f"  no unconsumed actual matched expected {want!r}")
                    else:
                        details.append(f"  no remaining actual for expected {want!r}")
                else:
                    consumed.add(matched_idx)
            if all_match:
                print(f"PASS {sig_id}  — {note}")
                pass_n += 1
            else:
                print(f"FAIL {sig_id}  — {note}")
                for d in details:
                    print(d)
                for g in got_list:
                    print(f"    actual: {json.dumps(g)}")
                fail_n += 1

    total = pass_n + fail_n
    print(f"\n{pass_n}/{total} passed, {fail_n} failed")
    return 0 if fail_n == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", type=Path, default=AGENT_DIR / "examples/feed.synthetic.txt")
    ap.add_argument("--golden", type=Path, default=AGENT_DIR / "examples/expected.synthetic.jsonl")
    ap.add_argument(
        "--offline",
        type=Path,
        default=None,
        help="Skip the agent run; diff this captured runner-output file instead.",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Max seconds for the agent run before killing it (default: 120).",
    )
    args = ap.parse_args()

    if not args.golden.exists():
        sys.stderr.write(
            f"[validate] golden not found: {args.golden}\n"
            f"  run: python {Path(__file__).parent}/gen_synthetic.py\n"
        )
        return 2

    if args.offline:
        text = args.offline.read_text()
    else:
        if not args.feed.exists():
            sys.stderr.write(
                f"[validate] feed not found: {args.feed}\n"
                f"  run: python {Path(__file__).parent}/gen_synthetic.py\n"
            )
            return 2
        try:
            text = run_agent(args.feed, timeout=args.timeout)
        except subprocess.TimeoutExpired as e:
            sys.stderr.write(
                f"[validate] runner exceeded {args.timeout:.0f}s timeout — killed.\n"
                f"  partial stdout:\n{(e.stdout or b'').decode('utf-8', 'replace')[:500]}\n"
            )
            return 3

    actuals = parse_agent_output(text)
    return validate(actuals, args.golden)


if __name__ == "__main__":
    raise SystemExit(main())
