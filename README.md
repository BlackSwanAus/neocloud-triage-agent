# Hyperstack Triage Agent

A long-running Claude agent that consumes a feed of GPU-fleet signals (kernel logs,
Xid events, manifest metadata) and emits structured AI findings.

## Layout

```
agent/
├── AGENT.md              # Agent system prompt + operating loop contract
├── runner.py             # Feed-driven loop (Claude Agent SDK)
├── skills/               # Bundled skills (deployable form)
│   ├── ai-finding-format/
│   ├── critical-log-patterns/   (+ source-patterns.tsv canonical from Go)
│   ├── evidence-citation/       (+ source-artifact-paths.txt canonical)
│   ├── fingerprint-correlation/
│   ├── hyperstack-triage/
│   ├── rma-decision/
│   ├── terraform-hyperstack/
│   └── xid-catalog/             (+ source-codes.tsv canonical from Go)
└── examples/
    └── feed.sample.txt   # Five signals + shutdown
```

The `references/source-*.{tsv,json,txt}` files in each skill are extracted from the
gather-info Go source (`hyperstack-support-scripts`) and are the authoritative catalog.
The `references/*.{tsv,md}` files are the curated subset with Hyperstack overrides.
The agent prefers curated when both exist; falls back to canonical when not.

## Install

Proof-of-concept uses **Claude Max** credentials via the `claude` CLI — no API key.

```bash
# 1. Claude Code CLI (handles auth)
npm i -g @anthropic-ai/claude-code
claude login                     # opens browser → log in with Max account

# 2. Python SDK (uses the CLI's stored credentials)
pip install claude-agent-sdk
```

Verify auth:
```bash
claude --version
claude -p "say hi"               # should respond without prompting for key
```

The SDK shells out to `claude` for inference; if `claude` is logged in, the runner
will use those Max credentials. Do **not** set `ANTHROPIC_API_KEY` — if it's set,
the CLI prefers it over the Max session and you'll burn API credits instead.

## Run

Feed from stdin (interactive):
```bash
python runner.py < examples/feed.sample.txt
```

Feed from a named pipe (production):
```bash
mkfifo /var/run/triage.fifo
python runner.py --feed /var/run/triage.fifo &
# producer:
tail -F /var/log/messages | log-to-signals.py > /var/run/triage.fifo
```

Default model is **`claude-haiku-4-5-20251001`** — verified by benchmark to resolve
hot Xids and known log patterns in **1 turn** when AGENT.md inlines the catalogs.
Upgrade to Sonnet/Opus only for ambiguous cases:
```bash
TRIAGE_MODEL=claude-sonnet-4-6 python runner.py < examples/feed.sample.txt
TRIAGE_MODEL=claude-opus-4-7   python runner.py < examples/feed.sample.txt
```

### Max-plan caveats (PoC only)

- **Usage limits apply** — Max session has a 5-hour rolling cap; a continuous
  triage loop can hit it. For long burns, pause the feed or downgrade to Haiku.
- **No managed-agents endpoint** — the Managed Agents API requires a workspace API
  key (`sk-ant-...`); Max credentials don't grant access. The local SDK path
  (this `runner.py`) is the only path that works with Max auth.
- **No prompt-cache billing visibility** — caching still happens, but you won't
  see token accounting; Max is flat-rate within limits.

## Feed protocol

Newline-delimited. Each block is one of:

```
SIGNAL <id>
<raw log lines / Xid event / JSON>
END
```

```
MANIFEST {"vfio_passthrough": true, "node": "h100-04", ...}
```

```
SHUTDOWN
```

`MANIFEST` is sticky context (sets VFIO suppression etc.) until replaced.
`SIGNAL` blocks trigger triage; the agent emits findings then `READY`.
`SHUTDOWN` flushes and exits.

## Output

For each SIGNAL the agent emits to stdout:

```
FINDING <signal-id>
{"family": "XID", "code": 48, "severity": "critical", "action": "reset-gpu", ...}
{"family": "PCIE_AER_FATAL", "severity": "critical", "bdf": "0000:1a:00.0", ...}
END
READY
```

Zero-finding (benign / suppressed) signals emit just `END\nREADY`.

## Synthetic test harness

`examples/gen_synthetic.py` generates a deterministic feed plus a golden
expectations file; `examples/validate.py` runs the agent against the feed and
diffs findings against the golden.

```bash
# Generate the synthetic feed + goldens (deterministic, seed=42)
python examples/gen_synthetic.py --scenarios all

# Run agent + validate in one go (requires `claude login`)
python examples/validate.py

# Or capture runner output and validate offline (no Max usage)
python runner.py < examples/feed.synthetic.txt > /tmp/run.out
python examples/validate.py --offline /tmp/run.out
```

Scenario sets (pick with `--scenarios`):

| Set | What it exercises |
|---|---|
| `smoke`   | Known Xids (48, 79, 92), HARD_LOCKUP, MLX5_FW_FATAL |
| `rma`     | Paired criticals on same BDF → must set `rma_candidate: true` |
| `vfio`    | VFIO on: fabric-mgr + solo SXid suppressed; flip off → emitted |
| `unknown` | Unknown Xid codes (must not invent severity), secret scrubbing, burst aggregation with truncation at 50 |
| `all`     | All four, seeded independently for reproducibility |

The golden uses partial matching: only fields named in `expected_findings` must
match; the agent may include additional fields (count, first_seen, evidence,
etc.). `_verbatim_must_not_contain` is a special key that asserts a secret was
scrubbed from the emitted `evidence.verbatim`.

## Production path (post-PoC)

Once the loop and skill behaviour are validated under Max, the move to production
is a credentials swap, not a rewrite:

1. Provision an Anthropic workspace API key (`sk-ant-...`).
2. **Option A — keep this runner.py:** `export ANTHROPIC_API_KEY=...` and unset
   the `claude` CLI login. Same code path, billed per-token.
3. **Option B — Managed Agents API:** upload `agent/skills/` as a custom skill
   bundle (one upload per skill subdir), create an agent with `system_prompt` =
   `AGENT.md`, `skills` = the uploaded ids, `tools` = `agent_toolset_20260401`
   (bash, read, glob, grep). Create a session, POST each feed block as a
   `user.message` event to `/v1/agents/sessions/{id}/events` with header
   `anthropic-beta: managed-agents-2026-04-01`, stream `agent.message` SSE
   events back.

See `re/research-managed-agents.md` for the full event flow, pricing, and tool
confirmation patterns.
