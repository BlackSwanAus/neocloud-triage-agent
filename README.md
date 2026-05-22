# Neocloud Triage Agent

A long-running Claude agent that consumes a feed of GPU-fleet signals
(kernel logs, NVIDIA Xid events, manifest metadata) and emits structured
findings via the Claude Agent SDK.

Not a production tool — an exploration of prompt-as-contract design, TDD
against a non-deterministic backend, and measurement-driven prompt
optimisation. See [`NOTICE.md`](NOTICE.md) for provenance.

---

## What it does

### Pipeline (per signal)

```
                                       ┌────────────────────────┐
SIGNAL <id>  ──►  classify  ──hit──►   │ inline hot table       │  ──►  emit FINDING
   raw text       (1 turn)             │   • 21 Xid codes       │       (1 turn total)
                                       │   • 19 log families    │
                                       └────────────────────────┘
                       │
                       └── miss ──►  Read skills/<name>/references/...
                                           │
                                           ▼
                                      classify, then emit FINDING
                                      (2–3 turns total)
```

For every block on the feed:

1. **Classify.** Match the raw text against AGENT.md's two inlined catalogs.
   - Numeric `Xid (PCI:<bdf>): <code>` events → look up `<code>` in the
     21-entry Xid hot table to resolve `family`, `severity`, `action`.
   - Kernel/syslog/journal lines → regex-match the 19 log family patterns
     (kernel panic, hard lockup, GPU off-bus, EDAC UE/CE, PCIe AER, NVMe
     controller down, MLX5 firmware fatal, EXT4/XFS errors, etc.).
   - Misses fall back to a single `Read` of the canonical TSV in
     `skills/xid-catalog/` or `skills/critical-log-patterns/`.

2. **Extract BDF.** Any PCIe/GPU line gets its bus:device.function pulled out
   with `[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]` and attached to
   `evidence.bdf`. Without a BDF the dashboard can't dedupe across archives,
   so this is mandatory for GPU signals.

3. **Apply context rules.** The sticky `MANIFEST` block sets archive-wide
   context:
   - `vfio_passthrough: true` suppresses `NVIDIA_FABRIC_MANAGER_NOT_RUNNING`
     (it's expected when NVSwitch is passthrough'd to a guest).
   - `vfio_passthrough: true` also suppresses solo SXid events — an SXid
     without a matching GPU Xid on the same fabric within 10 s is the
     fabric isolating itself correctly, not a fault.

4. **Apply escalation thresholds.** Some families upgrade severity based on
   rate (e.g. `EDAC_CE > 50/day` → `alert`, `PCIE_AER_CORRECTABLE > 50/24h`
   → `alert`). Originals are preserved in `severity_upgraded_from`.

5. **Aggregate.** Multiple matches of the same `(family, bdf)` collapse into
   one finding with `count`, `first_seen`, `last_seen`. Hard cap of 50
   findings per (family, bdf) per archive; past that, `truncated: true`.

6. **Scrub.** The raw line that goes into `evidence.verbatim` runs through
   secret-suppression regexes (AWS keys, bearer tokens, generic
   `password=…`) — matches replaced with `<REDACTED>`.

7. **Decide.** A `critical` severity authorises "investigate", **not** RMA.
   RMA requires a second independent critical signal on the same BDF within
   the archive. When satisfied, the second finding sets `rma_candidate: true`.

8. **Emit.** One `FINDING <signal-id>` block per turn; one JSON object per
   line inside; terminate with `END` and `READY`. The harness reads `READY`
   as "ready for next signal".

### Signal taxonomy

| Family | Source | Example trigger |
|---|---|---|
| `XID` (codes 8–154) | NVRM driver | `NVRM: Xid (PCI:0000:18:00.0): 48` (ECC DBE → reset GPU) |
| `KERNEL_PANIC` / `HARD_LOCKUP` / `SOFT_LOCKUP` | kernel | `Kernel panic - not syncing` |
| `GPU_BUS_DOWN` | NVRM / pcieport | `GPU at PCI:… has fallen off the bus` |
| `EDAC_UE` / `EDAC_CE` | EDAC | `EDAC MC0: 1 UE memory read error` |
| `MCE_HW_ERROR` | mcelog | `mce: [Hardware Error]` |
| `PCIE_AER_FATAL` / `_NONFATAL` / `_CORRECTABLE` | pcieport | `PCIe Bus Error: severity=Uncorrectable (Fatal)` |
| `NVME_CONTROLLER_DOWN` / `NVME_NOT_READY` | nvme driver | `nvme nvme0: controller is down` |
| `EXT4_FS_ERROR` / `XFS_CRC_ERROR` / `FS_REMOUNT_RO` | filesystem | `EXT4-fs error (device ...)` |
| `MLX5_FW_FATAL` | mlx5 | `mlx5_core 0000:c1:00.0: ... firmware fatal error` |
| `NVIDIA_FABRIC_MANAGER_NOT_RUNNING` | systemd | `nvidia-fabricmanager.service: Unit not found` (suppressed under VFIO) |
| `UNKNOWN_XID` / `UNKNOWN_LOG` | fallback | code/pattern not in catalog → severity=warning, action=escalate-for-review |

### Output schema

Required fields:

| Field | Type | Notes |
|---|---|---|
| `family` | string | From the catalog. `UNKNOWN_*` for unrecognised input. |
| `severity` | `info` \| `warning` \| `critical` | From catalog; may be upgraded by thresholds. |
| `action` | enum | `none` \| `monitor` \| `restart-app` \| `reset-gpu` \| `reboot-node` \| `escalate-for-review` \| `contact-support` |
| `evidence.verbatim` | string | First matched line, secret-scrubbed. |

Optional:

| Field | Type | Notes |
|---|---|---|
| `code` | int | Xid numeric code |
| `bdf` | string | PCI bus:device.function |
| `count`, `first_seen`, `last_seen` | int / iso8601 | Aggregation metadata |
| `truncated` | bool | True when count > 50 |
| `rma_candidate` | bool | Second independent critical on same BDF |
| `severity_upgraded_from` / `upgrade_reason` | string | Escalation audit trail |

Forbidden in agent output (provenance is added by the harness, not the
model): `prompt_hash`, `skills_loaded`, `model_version`, `archive_id`,
`created_at`, `confidence`.

### Skills bundled

The agent ships with eight skill packs under `skills/`. Most operate as
**reference fallback** — the model only Reads them on a hot-table miss.

| Skill | Role | When consulted |
|---|---|---|
| `xid-catalog` | Xid code → name/severity/action | Code not in inlined hot table |
| `critical-log-patterns` | Regex → log family/severity | Log line not matching inlined patterns |
| `neocloud-triage` | Operating procedure, escalation thresholds | Rate-based severity upgrade |
| `evidence-citation` | Artifact paths, secret-scrub patterns | Building `evidence` block |
| `ai-finding-format` | JSON schema + struct shapes | Output validation |
| `rma-decision` | 2-signal RMA gate, decision tree | Confirming RMA candidacy |
| `fingerprint-correlation` | Cross-archive dedup heuristics | Aggregate analysis (not single-signal) |
| `terraform-neocloud` | VM provisioning schema | Manifest/topology queries |

Each skill has two flavours of reference data side-by-side: the curated
`references/<name>.{tsv,md}` (selective, with operator overrides) and the
canonical `references/source-<name>.{tsv,json,txt}` (extracted from the Go
support binary — see [`NOTICE.md`](NOTICE.md)).

---

## Repository layout

```
.
├── AGENT.md              Agent system prompt — read this before changing behaviour
├── runner.py             Feed-driven loop (stdin or FIFO → ClaudeSDKClient)
├── skills/               Eight bundled skill packs (xid-catalog, log-patterns, …)
├── examples/
│   ├── feed.sample.txt           Hand-written 5-signal feed
│   ├── feed.synthetic.txt        Generated fixture (committed)
│   ├── expected.synthetic.jsonl  Golden expectations (committed)
│   ├── gen_synthetic.py          Deterministic generator (seed=42)
│   └── validate.py               Runs runner + diffs against golden
├── tests/
│   ├── test_validator.py         Parser + matcher unit tests
│   ├── test_validator_hit_dup.py Regression: each actual matches at most one expected
│   ├── test_validate_timeout.py  Subprocess timeout
│   ├── test_sdk_smoke.py         Live: SDK + Max-auth smoke
│   ├── test_output_protocol.py   Live: model still emits FINDING/END/READY
│   └── test_perf_baseline.py     Live: per-signal wall / turns / cost
├── CLAUDE.md             Notes for future Claude Code sessions in this repo
├── NOTICE.md             Provenance, attribution, what's authored vs derived
└── LICENSE               MIT
```

See [`AGENT.md`](AGENT.md) for the system prompt and the full input/output
contract. See [`CLAUDE.md`](CLAUDE.md) for working-in-the-repo conventions.

---

## Install

PoC uses **Claude Max** credentials via the `claude` CLI — no API key.

```bash
# 1. Claude Code CLI (provides auth)
npm i -g @anthropic-ai/claude-code
claude login                                  # opens browser, log in with Max

# 2. Python venv + SDK
python3 -m venv .venv
.venv/bin/pip install claude-agent-sdk pytest pytest-asyncio
```

**Critical:** the `claude` CLI prefers `ANTHROPIC_API_KEY` over the stored Max
session if both are present. To use Max, ensure the env var is **unset**:

```bash
unset ANTHROPIC_API_KEY        # or set it empty in the run command
```

---

## Run

Stdin feed:
```bash
.venv/bin/python runner.py < examples/feed.sample.txt
```

FIFO feed (deployment style):
```bash
mkfifo /var/run/triage.fifo
.venv/bin/python runner.py --feed /var/run/triage.fifo &
tail -F /var/log/messages | your-log-to-signal-shim > /var/run/triage.fifo
```

Override model:
```bash
TRIAGE_MODEL=claude-sonnet-4-6 .venv/bin/python runner.py < feed.txt
```

---

## Feed protocol

Newline-delimited blocks. Three block types:

```
SIGNAL <id>
<raw lines: kernel log, Xid event, JSON, whatever>
END
```
```
MANIFEST {"vfio_passthrough": true, "node": "h100-04", ...}
```
```
SHUTDOWN
```

`MANIFEST` is sticky context (controls VFIO suppression, hostname tagging,
etc.) until replaced. `SIGNAL` blocks trigger one round of triage and the
agent answers with a `FINDING` block:

```
FINDING <signal-id>
{"family": "XID", "code": 48, "severity": "critical", "action": "reset-gpu", "bdf": "0000:18:00.0", "evidence": {"verbatim": "..."}}
END
READY
```

Zero-finding (benign or suppressed) signals emit just `FINDING <id>\nEND\nREADY`.

---

## Tests

```bash
# Unit suite — no model calls, ~1.5s, free
.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_sdk_smoke.py \
  --ignore=tests/test_output_protocol.py \
  --ignore=tests/test_perf_baseline.py

# Live tests — hit the real model. Each one costs ~$0.02–$0.14 of Max usage.
RUN_LIVE_AGENT_TESTS=1 ANTHROPIC_API_KEY= \
  .venv/bin/python -m pytest tests/test_sdk_smoke.py tests/test_output_protocol.py -v -s
```

### Synthetic feed harness

```bash
.venv/bin/python examples/gen_synthetic.py --scenarios all  # regenerate fixtures
.venv/bin/python examples/validate.py                       # run agent + diff
.venv/bin/python examples/validate.py --offline /tmp/out.txt # diff captured output
```

Scenario sets:

| Set | Exercises |
|---|---|
| `smoke` | Known Xids (48, 79, 92), HARD_LOCKUP, MLX5_FW_FATAL |
| `rma` | Paired criticals on same BDF → must set `rma_candidate: true` |
| `vfio` | VFIO on: fabric-mgr + solo SXid suppressed; flip off → emitted |
| `unknown` | Unknown codes (no severity invention), secret scrubbing, burst aggregation + 50-finding cap |
| `all` | All four, seeded independently |

The golden uses **partial matching**: every field in `expected_findings` must
match the actual; the actual may include additional fields. The matcher
enforces that each actual finding satisfies at most one expected (no
double-counting). `_verbatim_must_not_contain` asserts a secret was scrubbed
from `evidence.verbatim`.

---

## Benchmarks

```bash
# Record a baseline (3 signals, ~3 min, ~$0.30 of Max usage)
RUN_LIVE_AGENT_TESTS=1 ANTHROPIC_API_KEY= BENCH_TAG=baseline \
  .venv/bin/python -m pytest tests/test_perf_baseline.py -v -s

# After a change to AGENT.md, re-run with a fresh tag
BENCH_TAG=after-change … pytest tests/test_perf_baseline.py
```

Results append to `tests/bench_log.jsonl` (gitignored — append-only and grows
on every live run).

Recorded improvement from inlining catalog hot-tables into `AGENT.md`
(measured on Haiku 4.5):

| signal | baseline | optimised |
|---|---|---|
| hot Xid 48 | 41.3s / 7 turns / $0.089 | 8.5s / 1 turn / $0.024 |
| cold Xid 119 | 45.5s / 6 turns / $0.094 | 12.3s / 1 turn / $0.022 |
| log GPU_BUS_DOWN | 79.3s / 11 turns / $0.138 | 34.4s / 1 turn / $0.035 |

---

## Limitations

- **Max-plan only as a PoC.** Max has a 5-hour rolling cap; long burns will
  hit it. The same `runner.py` works with an API key (`export
  ANTHROPIC_API_KEY=…`) for production deployment.
- **Single-signal turns.** The agent processes one `SIGNAL` per turn and does
  not currently correlate across signals beyond a single batch. Multi-archive
  fingerprint correlation is referenced by the `fingerprint-correlation`
  skill but the runner does not invoke it.
- **No real archive parsing.** The agent reads raw log lines and Xid events
  as text. It does not currently open `.tar.gz` gather-info archives — that
  would be added at the shim layer feeding the FIFO.
- **Provenance fields are forbidden in output** because the model would
  otherwise hallucinate `prompt_hash`, `skills_loaded`, etc. The harness is
  expected to add real provenance after the model emits.

---

## Production path (post-PoC)

The same `runner.py` works against a workspace API key — set
`ANTHROPIC_API_KEY` and the SDK uses it. For Anthropic's hosted Managed
Agents API instead, upload `skills/` as a custom bundle, create an agent
with `system_prompt = AGENT.md`, and POST each feed block as a
`user.message` event. The output contract is unchanged.

---

## License & attribution

MIT for everything authored here ([`LICENSE`](LICENSE)). Catalog data was
extracted from a publicly-distributed NexGenCloud support binary and is
acknowledged in [`NOTICE.md`](NOTICE.md). NVIDIA Xid codes, Linux kernel log
patterns, and the underlying conventions are public information.

Built with [Anthropic's Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).
