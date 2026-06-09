# Notice & Provenance

## What was authored fresh

Released under MIT (see `LICENSE`):

- `runner.py` — feed-driven Claude Agent SDK loop
- `AGENT.md` — system prompt and operating contract
- `examples/gen_synthetic.py` — synthetic signal-feed generator
- `examples/validate.py` — golden-comparison harness
- `tests/` — all unit, smoke, protocol, and performance tests
- `README.md`, `CLAUDE.md`, `NOTICE.md`
- `skills/rma-decision/SKILL.md` — RMA decision policy (no upstream source)

## Provenance of `skills/` reference data

The `skills/<name>/references/source-*.{tsv,json,txt}` files were extracted
from a publicly-distributed vendor support binary
(the vendor support-scripts repo) by parsing exported strings and Go AST nodes.
They reflect that binary's catalog of NVIDIA Xid codes, kernel log regex
patterns, evidence-collection paths, and JSON struct shapes.

The curated `references/*.{tsv,md}` files (without the `source-` prefix) are
a selective curation of the above, with notes on operator overrides and
escalation behaviour. Severity classifications are an interpretation — they
are not authoritative vendor policy.

## Underlying public data

- **NVIDIA Xid codes** are published in NVIDIA's GPU debugging documentation.
- **Linux kernel log patterns** are standard and published in `dmesg(1)`
  output and kernel source.

## Not in this repository

- No customer data, telemetry, or archives.
- No vendor-internal source code or documentation.
- No credentials, API keys, or production endpoints.

## Trademarks

"Claude" is a trademark of Anthropic PBC. "NVIDIA", "Xid", "SXid",
and "NVLink" are trademarks of NVIDIA Corporation. Use of these names does
not imply affiliation or endorsement.
