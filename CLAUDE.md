# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A long-running Claude agent that ingests a feed of GPU-fleet signals (kernel logs,
Xid/SXid events, manifest blobs) and emits structured AI findings. Built on
`claude-agent-sdk`, designed for a development PoC using **Claude Max credentials**
via the `claude` CLI (no API key).

## Commands

### Setup
```bash
python3 -m venv .venv && .venv/bin/pip install claude-agent-sdk pytest pytest-asyncio
claude login          # one-time; SDK shells out to claude CLI for auth
```

### Run the agent loop
```bash
.venv/bin/python runner.py < examples/feed.sample.txt          # stdin
.venv/bin/python runner.py --feed /var/run/triage.fifo         # named pipe
TRIAGE_MODEL=claude-sonnet-4-6 .venv/bin/python runner.py < …  # override model
```

### Tests
```bash
# Unit suite (14 tests, no model calls, ~1.5s)
.venv/bin/python -m pytest tests/ --ignore=tests/test_sdk_smoke.py \
                                  --ignore=tests/test_output_protocol.py \
                                  --ignore=tests/test_perf_baseline.py

# Live SDK smoke (1 query, ~10s, uses Max session)
RUN_LIVE_AGENT_TESTS=1 ANTHROPIC_API_KEY= .venv/bin/python -m pytest tests/test_sdk_smoke.py -v -s

# Live output-protocol regression
RUN_LIVE_AGENT_TESTS=1 ANTHROPIC_API_KEY= .venv/bin/python -m pytest tests/test_output_protocol.py -v -s

# Single test
.venv/bin/python -m pytest tests/test_validator.py::test_strips_code_fences -v
```

**Critical:** live tests require `ANTHROPIC_API_KEY=` to be **unset** (note the trailing
`=`). If the env var is set, the `claude` CLI prefers it and bills the API account
instead of using the Max session.

### Benchmarks
```bash
# Baseline current AGENT.md (3 signals, ~3min, ~$0.30 API-equivalent)
RUN_LIVE_AGENT_TESTS=1 ANTHROPIC_API_KEY= BENCH_TAG=baseline \
  .venv/bin/python -m pytest tests/test_perf_baseline.py -v -s

# After a change, re-run with a different tag
BENCH_TAG=optimized … pytest tests/test_perf_baseline.py
```
Results append to `tests/bench_log.jsonl` (gitignored — append-only, grows
unboundedly across runs).

### Synthetic data
```bash
.venv/bin/python examples/gen_synthetic.py --scenarios all     # regenerates fixtures
.venv/bin/python examples/validate.py                          # runs runner + diffs
.venv/bin/python examples/validate.py --offline /tmp/run.out   # diff captured output
.venv/bin/python examples/validate.py --timeout 60             # cap runner hang
```

## Architecture

### Data flow

```
feed (stdin/FIFO)
  │
  ▼
runner.py ── one block per turn ──> ClaudeSDKClient ── claude CLI ── Max session
                                         │
                                         ▼
                              system_prompt = AGENT.md
                                         │
                                         ▼
                              FINDING <id> / JSON / END / READY
                                         │
                                         ▼
                                   stdout / validator
```

### Three boundaries to understand

1. **Feed protocol** (`runner.py`): newline-delimited `SIGNAL <id>` … `END` blocks
   with sticky `MANIFEST {...}` context and `SHUTDOWN` sentinel. The runner forwards
   each block as one turn to a single long-lived `ClaudeSDKClient` session — state
   (manifest, conversation history) lives in the session.

2. **Agent contract** (`AGENT.md`): system prompt + inlined catalogs. The Xid hot
   table (21 codes) and critical-log family table (19 families) live inside
   `AGENT.md` itself so common signals resolve in **1 turn** with zero file reads.
   `skills/` are demoted to a fallback role — read only when the inline tables miss.
   This was validated by benchmark: turn count dropped from 6–11 → 1, wall time
   3.6× faster, cost 75% lower.

3. **Output contract** (parsed by `examples/validate.py`):
   ```
   FINDING <signal-id>
   {"family":"...", "severity":"...", "action":"...", ...}
   END
   READY
   ```
   Anything outside `FINDING…END` is treated as prose noise and ignored. Code-fence
   wrappers are tolerated. The validator does partial-match per expected finding,
   with **hit-tracking** — each actual finding can satisfy at most one expected.

### `skills/` provenance

Each skill has two reference flavours co-located:
- `references/<name>.{tsv,md}` — curated, with Hyperstack-specific overrides
  (severity bumps, action verbs, escalation rules)
- `references/source-<name>.{tsv,json,txt}` — extracted from the Go source
  (`hyperstack-support-scripts`), authoritative catalog

When NVIDIA's catalog drifts, regenerate `source-*` from upstream; treat curated
files as the override layer. **Do not** add files to `skills/<name>/references/`
without first asking whether the data belongs in the inlined hot tables in
`AGENT.md` instead — every file read costs a turn.

### Test layering

- `test_validator*.py`, `test_validate_timeout.py` — pure unit, no SDK calls
- `test_sdk_smoke.py` — verifies SDK installed + Max auth works
- `test_output_protocol.py` — verifies the model still emits the
  `FINDING/END/READY` contract after AGENT.md edits
- `test_perf_baseline.py` — instrumentation, not pass/fail; records
  wall-time / turns / cost to `bench_log.jsonl`

All live-running tests gate on `RUN_LIVE_AGENT_TESTS=1` to keep CI/local dev free.

## Gotchas

- **Model default is `claude-haiku-4-5-20251001`**, set in `runner.py` and the
  benchmark. Verified by measurement to handle the inlined hot tables correctly in
  1 turn. Switching to Sonnet/Opus for routine triage is over-spec'd — use the env
  override only for cold-path signals or correlation work.

- **`max_turns ≥ 12`** is required when the model has to consult fallback skill
  files. The first version of `runner.py` shipped with `max_turns=4` and silently
  errored on any signal that needed a Read.

- **Skills are a context filter, not a sandbox.** The SDK's `skills=` option hides
  unlisted skills from the model's Skill-tool listing, but the files remain on disk
  and the model can still `Read` them. Don't store secrets in skill files.

- **Provenance fields are forbidden in output.** The model has a tendency to
  hallucinate `provenance.prompt_hash`, `skills_loaded`, `archive_id`. AGENT.md
  explicitly forbids these; if you see them re-emerge in output, the prompt has
  regressed.

- **`bench_log.jsonl` is append-only.** Delete it before a fresh baseline; don't
  commit it.

## Reference docs in-repo

- `README.md` — install, run, feed protocol, production-path migration
- `AGENT.md` — the system prompt (read this before changing model behaviour)
- `examples/gen_synthetic.py` — scenario taxonomy (smoke / rma / vfio / unknown)
