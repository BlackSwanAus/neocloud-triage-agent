#!/usr/bin/env python3
"""Resolve an Xid code or SXid name to severity + action.

Usage:
  lookup.py 48
  lookup.py NVLINK_TREX_ERROR
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODES = HERE.parent / "references" / "codes.tsv"


def lookup(query: str) -> dict | None:
    query = query.strip()
    # Xid numeric
    if query.isdigit():
        code = int(query)
        with CODES.open() as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                if int(row["code"]) == code:
                    return {"kind": "xid", **row}
        return None
    # SXid: caller must read references/sxid.md for the table; this script
    # only normalises the name and returns a stub.
    name = query.upper().replace(" ", "_")
    return {"kind": "sxid", "name": name, "lookup": "see references/sxid.md"}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: lookup.py <code-or-name>", file=sys.stderr)
        return 2
    result = lookup(sys.argv[1])
    if result is None:
        print(f"UNKNOWN_XID\twarning\tescalate-for-review")
        return 1
    if result["kind"] == "xid":
        print(f"{result['name']}\t{result['severity']}\t{result['action']}")
    else:
        print(f"{result['name']}\tsee-sxid-references")
    return 0


if __name__ == "__main__":
    sys.exit(main())
