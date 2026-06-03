#!/usr/bin/env python3
"""
End-to-end validation for the DCGM telemetry path.

Runs the generated DCGM feed (poller output) through runner.py and diffs the
agent's findings against the golden, reusing examples/validate.py's matcher.

This hits the live model — run with Max auth:
  RUN_LIVE_AGENT_TESTS=1 ANTHROPIC_API_KEY= python examples/dcgm/validate_dcgm.py

Regenerate the feed first if you changed the poller or scenarios:
  python examples/dcgm/gen_dcgm_synthetic.py

Usage:
  python examples/dcgm/validate_dcgm.py
  python examples/dcgm/validate_dcgm.py --offline /tmp/dcgm_run.out
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "examples"))

import validate  # noqa: E402  (reuse run_agent / parse_agent_output / validate)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", type=Path, default=HERE / "feed.dcgm.txt")
    ap.add_argument("--golden", type=Path, default=HERE / "expected.dcgm.jsonl")
    ap.add_argument("--offline", type=Path, default=None,
                    help="diff a captured runner-output file instead of running the agent")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    if not args.golden.exists() or not args.feed.exists():
        sys.stderr.write(
            f"[validate_dcgm] missing fixtures — run:\n"
            f"  python {HERE / 'gen_dcgm_synthetic.py'}\n"
        )
        return 2

    if args.offline:
        text = args.offline.read_text()
    else:
        try:
            text = validate.run_agent(args.feed, timeout=args.timeout)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[validate_dcgm] runner failed: {e}\n")
            return 3

    actuals = validate.parse_agent_output(text)
    return validate.validate(actuals, args.golden)


if __name__ == "__main__":
    raise SystemExit(main())
