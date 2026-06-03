# NVIDIA DCGM-Exporter Integration — Design & Reference

**Status:** Design (approved via brainstorming, 2026-06-03). Implementation pending.
**Author:** brad@nimbus.net.au
**Scope:** Add NVIDIA DCGM-exporter as a telemetry source for the Neocloud Triage
Agent, producing *valid* (trustworthy, deduplicated, actionable) findings from
continuous GPU metrics.

---

## 1. Why this exists

Today the agent triages **discrete events**: kernel log lines, NVRM Xid/SXid
events, and manifest blobs arrive as `SIGNAL … END` text blocks on a feed, and
the agent classifies each against the inlined hot tables in `AGENT.md`. Each
signal is a thing that *happened once* and was already written to a log.

GPU fleets emit a second, fundamentally different class of health information:
**continuous telemetry**. Temperature, power draw, ECC error counters, NVLink
CRC counts, PCIe replay counts, throttle state, and retired-page counts are
sampled by hardware and exposed as numbers that change every second. Many of the
most actionable fault signals — a double-bit ECC error, a GPU crossing its
thermal shutdown limit, an NVLink degrading — surface in telemetry *before or
instead of* a clean log line. A triage agent blind to telemetry is missing the
sensor that most directly observes silicon health.

[NVIDIA DCGM](https://docs.nvidia.com/datacenter/dcgm/latest/) (Data Center GPU
Manager) is the vendor-standard way to read that telemetry, and
[`dcgm-exporter`](https://github.com/NVIDIA/dcgm-exporter) is the component that
publishes it in Prometheus exposition format over HTTP. It is the de-facto
standard in Kubernetes GPU clusters (it ships with the NVIDIA GPU Operator) and
on bare-metal neocloud nodes. Integrating it gives the agent a direct,
vendor-supported view of GPU health.

### What "valid telemetry" means here

Raw telemetry is *not* directly useful to a triage agent. A naive integration
that emitted a finding for every bad-looking sample would flood the feed with
duplicates, flap on threshold boundaries, and fire spuriously on exporter
restarts. The work in this document is mostly about turning a firehose of
numeric gauges into a small stream of **valid** triage signals:

- **Deduplicated** — one signal per real event, not one per scrape.
- **Restart-safe** — a fault already reported does not re-fire when the poller
  or exporter restarts.
- **Non-flapping** — a gauge hovering at its threshold does not oscillate.
- **Noise-gated** — transient throttle blips do not become findings; only
  persistent conditions do.
- **Correlatable** — every GPU signal carries a canonical BDF so telemetry
  findings line up with log/Xid findings on the same device.
- **Corroboration-gated for RMA** — telemetry can *contribute* a second
  independent signal toward an RMA decision but never authorises RMA alone.

Those properties are the design, not an afterthought.

---

## 2. Goals and non-goals

### Goals

1. Scrape a `dcgm-exporter` `/metrics` endpoint (or a committed fixture) and turn
   notable telemetry into `SIGNAL` blocks the existing `runner.py` consumes
   unchanged.
2. Teach `AGENT.md` a DCGM catalog so telemetry signals resolve in **1 turn**
   with zero file reads, matching the existing hot-table performance contract.
3. Cover **health/error fields** (ECC, XID-via-DCGM, retired pages, row-remap,
   NVLink, PCIe replay, thermal/power violation) **plus saturation thresholds**
   on continuous gauges (GPU/memory temperature, persistent throttle).
4. Stay **fixture-driven** for dev/test so the offline suite remains hermetic and
   free; the live HTTP scrape path is implemented but only exercised against a
   real exporter.

### Non-goals (YAGNI)

- **Not** a general Prometheus/monitoring replacement. We ingest a curated set of
  health-relevant fields, not the full DCP profiling surface (SM activity, DRAM
  activity, PCIe throughput, occupancy). Utilization/capacity metrics are
  explicitly out of scope for v1.
- **Not** an alerting system. No Alertmanager, no routing, no paging. The agent
  emits findings; the harness/dashboard decides what to do with them.
- **No cross-node correlation.** The poller is per-endpoint (per-node). Fleet-wide
  fingerprint correlation remains the concern of the existing
  `fingerprint-correlation` skill and is not invoked here.
- **No new runtime dependencies.** Scraping uses the Python standard library
  (`urllib`); we do **not** pull in `prometheus_client`.

---

## 3. Architecture

The integration adds exactly **one new producer** in front of the existing
pipeline. The agent contract (`AGENT.md` output protocol) and `runner.py`'s feed
loop are structurally unchanged.

```
NVIDIA GPU(s)
   │  hardware counters / sensors
   ▼
DCGM (libdcgm)  ── dcgm-exporter ──►  HTTP :9400 /metrics   (Prometheus text)
                                              │
                  ┌───────────────────────────┤
                  │                            │
        (live)  --endpoint URL        (test) --fixture *.prom
                  │                            │
                  └───────────────┬────────────┘
                                  ▼
                        dcgm_poller.py   ◄── state.json (per-(field,bdf) memory)
                          1. parse exposition text
                          2. normalize pci_bus_id → canonical BDF
                          3. edge-detect (counter / gauge / persistence)
                          4. emit SIGNAL block per real event
                                  │
                                  │  SIGNAL dcgm-NNNNN … END   (stdout or FIFO)
                                  ▼
                            runner.py   (unchanged)
                                  │
                                  ▼
                    AGENT.md + DCGM hot table → FINDING
                                  │
                                  ▼
                         stdout / examples/validate.py
```

### Division of responsibility

| Concern | Owner | Rationale |
|---|---|---|
| Scrape transport (HTTP / file) | poller | source-specific I/O |
| Prometheus text parsing | poller | source-specific format |
| BDF normalization | poller | mechanical string transform |
| Edge detection / dedup / state | poller | needs memory across scrapes; deterministic, testable without a model |
| Threshold *values* | poller (source of truth) | one place; documented in skill |
| Classification (field → family/severity/action) | agent (`AGENT.md`) | this is the agent's existing job |
| RMA corroboration (2-signal rule) | agent | already implemented; telemetry just feeds it |

The poller does **no classification**. It decides only *"this reading is a new
event worth a signal"* and emits the raw DCGM sample line. The agent then
classifies it exactly as it classifies a log line — same FINDING/END/READY
contract, same hot-table-first performance profile. This keeps the two halves
independently testable: the poller's logic is pure Python (hermetic unit tests),
and the agent's classification is exercised by the existing live harness.

---

## 4. What dcgm-exporter emits

`dcgm-exporter` publishes one line per (metric, GPU) in Prometheus exposition
format. A representative slice:

```
# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C).
# TYPE DCGM_FI_DEV_GPU_TEMP gauge
DCGM_FI_DEV_GPU_TEMP{gpu="0",UUID="GPU-1d…",pci_bus_id="00000000:18:00.0",device="nvidia0",modelName="NVIDIA H100 80GB HBM3",Hostname="h100-04"} 71
DCGM_FI_DEV_ECC_DBE_VOL_TOTAL{gpu="0",pci_bus_id="00000000:18:00.0",modelName="NVIDIA H100 80GB HBM3"} 0
DCGM_FI_DEV_XID_ERRORS{gpu="3",pci_bus_id="00000000:3B:00.0",modelName="NVIDIA H100 80GB HBM3"} 0
```

Key properties the poller must handle:

- **Metric name is the stable key**, e.g. `DCGM_FI_DEV_GPU_TEMP`. (DCGM numeric
  *field IDs* exist but the exporter does not put them on the wire, and the
  IDs documented in `skills/evidence-citation/references/dcgm-fields.md` are
  illustrative — the integration keys off the **metric name**, which is what
  actually arrives, not the numeric ID.)
- **Labels** carry the device identity. We use `pci_bus_id` (always present),
  `gpu` (ordinal), `modelName`, and `Hostname` when present. In Kubernetes,
  additional `pod`/`namespace`/`container` labels may appear; we pass them
  through verbatim in the emitted line but key edge-detection on BDF.
- **`pci_bus_id` uses an 8-hex domain**, e.g. `00000000:3B:00.0`, upper-case.
  Linux/NVRM logs use a 4-hex domain, `0000:3b:00.0`. We normalize (see §6) so
  the agent's existing BDF regex matches and telemetry correlates with logs.
- **Counter vs gauge vs code** — three sub-types, handled differently (§5):
  - *Counters* (monotonic): `DCGM_FI_DEV_ECC_*_VOL_TOTAL`,
    `DCGM_FI_DEV_PCIE_REPLAY_COUNTER`, `DCGM_FI_DEV_NVLINK_*_ERROR_COUNT_TOTAL`,
    `DCGM_FI_DEV_THERMAL_VIOLATION`, `DCGM_FI_DEV_POWER_VIOLATION`,
    `DCGM_FI_DEV_RETIRED_*`.
  - *Gauges* (instantaneous): `DCGM_FI_DEV_GPU_TEMP`, `DCGM_FI_DEV_MEMORY_TEMP`.
  - *Code-valued* (special): `DCGM_FI_DEV_XID_ERRORS` — its value is the **last
    Xid code observed**, not a count. Requires dedicated handling (§5.4).
  - *Bitmask* (special): `DCGM_FI_DEV_CLOCK_THROTTLE_REASONS` /
    `DCGM_FI_DEV_CLOCKS_EVENT_REASONS` — a bitfield of active throttle reasons.

---

## 5. Edge detection — the core of validity

Edge detection is what converts continuous telemetry into discrete, valid
signals. State is keyed by `(metric_name, bdf)` and persisted to a JSON file so
the poller is restart-safe. Each metric class has its own rule.

### 5.1 Counters — emit on increase

For monotonic counters, emit a `SIGNAL` only when the value rises above the
last-seen value, and carry the `delta` into the emitted comment.

```
last = state.counters[key]            # default 0 on first sight
if value > last:    emit(delta = value - last)
state.counters[key] = value
```

- **First sighting** (no prior state) with a non-zero value emits once — a fault
  already present when the poller starts is real and should surface.
- **No change** between scrapes is silent. This is what kills the per-scrape
  duplicate flood.

### 5.2 Counter resets — robustness against restarts

`dcgm-exporter` or the GPU driver can restart, resetting a counter to 0 (or a
lower value). A naive `delta = value - last` would compute a huge negative
number or miss the reset. Standard Prometheus counter-reset handling:

```
if value < last:                      # counter went backwards → reset happened
    delta = value                     # treat current as the new delta from 0
    if value > 0: emit(delta)
state.counters[key] = value
```

This prevents both spurious giant deltas and silent loss of a post-restart
fault.

### 5.3 Gauges — threshold crossing with hysteresis

For instantaneous gauges (temperatures), we keep a `fired` flag per key and emit
only on the **below→above transition**, re-arming only after the value drops a
hysteresis band below the threshold:

```
T  = threshold[metric]                # e.g. GPU_TEMP 90°C
H  = hysteresis                       # 2°C
if value >= T and not fired:    emit(); fired = True
if value <  T - H and fired:    fired = False        # re-arm, no emit
```

A GPU sitting at 90–92°C for ten minutes produces **one** signal, not one per
scrape. It only re-fires after cooling below 88°C and crossing 90°C again. This
is the anti-flapping guarantee.

### 5.4 Code-valued field — `DCGM_FI_DEV_XID_ERRORS`

This field's value is the **last Xid code** the GPU reported (e.g. `48`), not a
counter. Treating it as a counter would be wrong (code `92` is not "more" than
code `48`). Rule:

```
prev = state.xid[key]                 # last code we emitted for this BDF
if value != 0 and value != prev:      # transitioned to a new non-zero code
    emit(code = value)
state.xid[key] = value
```

The emitted signal carries `code = <value>`, and the agent resolves the code
against the **existing Xid hot table** in `AGENT.md` (§7) — so a DCGM-observed
Xid 48 produces exactly the same `ECC_DBE / critical / reset-gpu` classification
as an NVRM-logged Xid 48, and the two corroborate each other for RMA.

### 5.5 Bitmask field — persistent throttle gate

`DCGM_FI_DEV_CLOCK_THROTTLE_REASONS` is a bitmask. We care about the
*hardware-fault* reasons (HW thermal slowdown, HW power brake, HW slowdown), not
benign software clock optimisation. Momentary throttling is normal; **persistent**
throttling is a finding. We require the relevant bits to stay set for
`min_consecutive` scrapes (default 3) before emitting:

```
bad = value & HW_FAULT_MASK
if bad: consecutive += 1 else: consecutive = 0
if consecutive == min_consecutive: emit()       # exactly once at the gate
```

This noise-gates transient blips out of the feed entirely.

### 5.6 State file

JSON, written atomically (temp file + `os.rename`) so a crash mid-write cannot
corrupt it:

```json
{
  "version": 1,
  "seq": 17,
  "counters": { "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL|0000:18:00.0": 1 },
  "xid":      { "DCGM_FI_DEV_XID_ERRORS|0000:3b:00.0": 48 },
  "gauges":   { "DCGM_FI_DEV_GPU_TEMP|0000:18:00.0": { "fired": true } },
  "throttle": { "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS|0000:18:00.0": { "consecutive": 3 } }
}
```

`seq` is a monotonic counter that makes emitted `SIGNAL` ids
(`dcgm-00017`) deterministic — important for reproducible test goldens.

---

## 6. BDF normalization

DCGM `pci_bus_id="00000000:3B:00.0"` → canonical `0000:3b:00.0`:

1. Lower-case the whole string.
2. Split on `:` and `.` → `domain`, `bus`, `dev`, `func`.
3. Truncate the 8-hex domain to its low 4 hex (`00000000` → `0000`).
4. Reassemble `dddd:bb:dd.f`.

The result matches the agent's existing extraction regex
`\b([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\b`, so no agent change is
needed and telemetry findings dedupe against log findings on the same device.

---

## 7. Agent catalog (`AGENT.md`)

A new hot-table section is added after the Xid and log-family tables. Severities
and thresholds are lifted verbatim from the operator policy already documented in
`skills/evidence-citation/references/dcgm-fields.md` — nothing invented.

```
DCGM metric                            | edge      | family                  | severity | action            | threshold / note
---------------------------------------+-----------+-------------------------+----------+-------------------+---------------------------
DCGM_FI_DEV_XID_ERRORS                 | code Δ    | XID (code = value)      | →Xid tbl | →Xid table lookup | delegates to Xid hot table
DCGM_FI_DEV_ECC_DBE_VOL_TOTAL          | counter↑  | DCGM_ECC_DBE            | critical | reset-gpu         | DBE>0; RMA candidate
DCGM_FI_DEV_ECC_SBE_VOL_TOTAL          | counter↑  | DCGM_ECC_SBE            | warning  | monitor           | escalate if >1000/hr
DCGM_FI_DEV_RETIRED_DBE                | counter↑  | DCGM_RETIRED_PAGES      | warning  | monitor           | >20 → RMA candidate
DCGM_FI_DEV_ROW_REMAP_FAILURE          | counter↑  | DCGM_ROW_REMAP_FAIL     | critical | reset-gpu         | uncorrectable; RMA candidate
DCGM_FI_DEV_PCIE_REPLAY_COUNTER        | counter↑  | DCGM_PCIE_REPLAY        | warning  | monitor           | >50 total → escalate
DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_*    | counter↑  | DCGM_NVLINK_ERRORS      | warning  | contact-support   | spike → link degradation
DCGM_FI_DEV_THERMAL_VIOLATION          | counter↑  | DCGM_THERMAL_VIOLATION  | warning  | monitor           | sustained → investigate
DCGM_FI_DEV_POWER_VIOLATION            | counter↑  | DCGM_POWER_VIOLATION    | warning  | monitor           | sustained → investigate
DCGM_FI_DEV_GPU_TEMP                   | gauge≥    | DCGM_GPU_OVERTEMP       | critical | reset-gpu         | ≥90°C (re-arm <88°C)
DCGM_FI_DEV_MEMORY_TEMP                | gauge≥    | DCGM_MEM_OVERTEMP       | critical | reset-gpu         | ≥95°C (re-arm <93°C)
DCGM_FI_DEV_CLOCK_THROTTLE_REASONS     | persist   | DCGM_PERSISTENT_THROTTLE| warning  | monitor           | HW bits, 3+ consecutive polls
```

Two deliberate decisions:

1. **XID-via-DCGM reuses the Xid table.** The DCGM catalog never restates Xid
   severities. `DCGM_FI_DEV_XID_ERRORS` value `48` → `family: XID, code: 48`,
   then look up `48` in the 21-entry Xid hot table. The two catalogs cannot
   drift apart because there is only one source of Xid truth.
2. **`DCGM_*` family prefix** distinguishes telemetry-derived findings from
   log-derived ones (`EDAC_CE`, `PCIE_AER_*`). They are the *same fault class
   seen through a different sensor*; operators want to know which sensor caught
   it, and a DCGM DBE plus a kernel Xid 48 on the same BDF is exactly the
   independent corroboration the 2-signal RMA rule wants.

---

## 8. Skill pack — `skills/dcgm-telemetry/`

Mirrors the `xid-catalog` structure: a `SKILL.md` lookup procedure plus
reference files. Read by the agent only on a hot-table miss.

```
skills/dcgm-telemetry/
├── SKILL.md                              # resolution order, field semantics, output contract
└── references/
    ├── dcgm-fields.tsv                    # curated: metric → family/severity/action + threshold (override layer)
    ├── source-dcgm-fields.tsv            # canonical metric list (regenerated from a dcgm-exporter CSV)
    └── thresholds.md                     # threshold rationale (temps, rates, persistence) + provenance
```

The curated/`source-` split follows the repo convention: `source-*` is the
authoritative catalog (here, the dcgm-exporter default counter CSV), and the
curated TSV is the neocloud override layer (severity bumps, action verbs, RMA
thresholds). Threshold *values* live canonically in `dcgm_poller.py`; the skill
documents the same numbers and the reasoning behind them.

> **Note:** `skills/evidence-citation/references/dcgm-fields.md` already exists
> and documents field meanings and RMA thresholds. The new pack reuses those
> numbers and cross-links to it rather than duplicating. The illustrative
> numeric field IDs in that file should be reconciled against NVIDIA's
> authoritative field-identifier list when `source-dcgm-fields.tsv` is first
> generated.

---

## 9. End-to-end example

**Scrape N** (fixture `h100-dbe.before.prom`): `ECC_DBE_VOL_TOTAL … 0`.
**Scrape N+1** (`h100-dbe.after.prom`): `ECC_DBE_VOL_TOTAL … 1`.

Poller detects a counter increase and emits:

```
SIGNAL dcgm-00017
# dcgm-exporter edge: counter DCGM_FI_DEV_ECC_DBE_VOL_TOTAL increased 0 -> 1 over 15s
DCGM_FI_DEV_ECC_DBE_VOL_TOTAL{gpu="0",pci_bus_id="00000000:18:00.0",modelName="NVIDIA H100 80GB HBM3"} 1
END
```

`runner.py` forwards it; the agent classifies against the DCGM hot table and
emits:

```
FINDING dcgm-00017
{"family": "DCGM_ECC_DBE", "severity": "critical", "action": "reset-gpu", "bdf": "0000:18:00.0", "evidence": {"verbatim": "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL{gpu=\"0\",pci_bus_id=\"00000000:18:00.0\",modelName=\"NVIDIA H100 80GB HBM3\"} 1"}}
END
READY
```

If a kernel-logged Xid 48 on `0000:18:00.0` arrives later in the same archive,
the agent's existing 2-signal rule sets `rma_candidate: true` on the second —
telemetry and logs corroborating one failing GPU.

---

## 10. Fixtures and synthetic data

Because edge-detection needs a "before" and "after", fixtures come in **paired
consecutive scrapes** under `examples/dcgm/`, generated deterministically by
`gen_dcgm_synthetic.py` (seed=42, same style as `gen_synthetic.py`).

| Scenario | Snapshots | Exercises |
|---|---|---|
| `dbe` | before/after | counter edge; `ECC_DBE` 0→1 and `XID_ERRORS` 0→48 same BDF (XID delegation + corroboration setup) |
| `overtemp` | 3 snaps | gauge crossing (87→93 emits) then drop (93→88 must **not** re-fire) — re-arm test |
| `throttle` | 3 snaps | HW throttle bit set across 3 polls — silent on 1–2, emit on 3 (persistence gate) |
| `quiet` | 1 snap | all-nominal → **zero** signals (no-false-positive test) |

Golden: `examples/dcgm/expected.dcgm.jsonl` lists the expected `SIGNAL` ids and
the agent finding each should yield, using the existing partial-match +
hit-tracking validator semantics.

---

## 11. Test plan

`tests/test_dcgm_poller.py` — **pure unit, no model calls**, joins the existing
free offline suite:

| Test | Asserts |
|---|---|
| `test_parse_metrics_line` | metric name, labels, value extracted from exposition text |
| `test_bdf_normalization` | `00000000:3B:00.0` → `0000:3b:00.0` |
| `test_counter_edge_emits_once` | increase emits with correct delta; flat re-scrape is silent |
| `test_counter_reset_handling` | value drop (restart) → re-baseline, no spurious delta |
| `test_gauge_threshold_crossing_and_rearm` | fire on cross, silent while high, re-arm after drop past hysteresis |
| `test_xid_code_transition` | new non-zero code emits with `code`; repeat is silent |
| `test_throttle_persistence_gate` | silent polls 1–2, fires on poll 3 |
| `test_state_roundtrip` | state persists; already-reported faults suppressed across "restart" |
| `test_quiet_scrape_zero_signals` | nominal snapshot emits nothing |
| `test_emitted_signal_parses_as_feed_block` | poller output is consumable by `runner.read_block` (contract glue) |

**Live (optional, gated `RUN_LIVE_AGENT_TESTS=1`):**
`examples/dcgm/validate_dcgm.py` pipes a generated fixture through
`dcgm_poller.py | runner.py` and diffs findings against the golden — end-to-end
proof that a real DBE telemetry event becomes a `critical / reset-gpu` finding.

---

## 12. Operational guidance

### Live wiring (deployment)

```bash
# dcgm-exporter typically runs as a DaemonSet (k8s) or systemd unit on :9400.
mkfifo /var/run/triage.fifo
python dcgm_poller.py \
    --endpoint http://localhost:9400/metrics \
    --state /var/lib/triage/dcgm.state \
    --interval 15 \
    --out /var/run/triage.fifo &

python runner.py --feed /var/run/triage.fifo
```

- **Scrape interval** should match or be a small multiple of the exporter's
  collection interval (default 30s in many deployments; `dcgm-exporter -d`
  controls it). The persistence gate's `min_consecutive` is in *poll* units, so
  document the wall-clock it implies (3 × 15s = 45s of sustained throttle).
- **State file** must be on persistent storage in production so the poller stays
  restart-safe across reboots. Per-node, not shared.
- **One poller per node/endpoint.** dcgm-exporter is node-local; run a poller
  beside each.

### Manifest context

dcgm-exporter metrics do not carry `vfio_passthrough`. VFIO context still arrives
via the existing `MANIFEST` mechanism from the manifest shim, independent of the
poller. The poller may optionally prepend a single `MANIFEST {"node": …,
"source": "dcgm-exporter"}` (from a `--node` flag) for tagging; it does not
attempt to infer VFIO state.

---

## 13. Security considerations

- **Telemetry is attacker-influenceable in theory** (a tenant workload can drive
  a GPU hot, spike NVLink errors, etc.), but it is **numeric** — the poller
  parses floats and bitmasks, never executes content. The emitted `SIGNAL` body
  is a re-serialized metric line, not free-form text.
- The agent's existing **default-deny tool gate** (`runner.py`,
  `TRIAGE_TOOL_ALLOWLIST = {Read, Glob, Grep}`, `setting_sources=[]`) applies
  unchanged. DCGM signals cannot widen the agent's capabilities.
- **No secrets in telemetry.** dcgm-exporter labels are device identity, not
  credentials. The existing verbatim secret-scrub still runs; if a custom label
  ever carried a secret, it would be redacted before landing in `evidence`.
- The poller writes only its state file and its output stream; it takes no input
  that can cause file writes elsewhere.

---

## 14. Limitations and future work

- **v1 covers health + saturation only.** Utilization/capacity telemetry (GPU
  util, FB used/free, SM/DRAM activity, PCIe throughput) is deliberately
  excluded; adding it means more fields, more thresholds, and more noise to tune.
- **Per-node, single-poller.** Cross-node correlation (e.g. an NVLink fabric
  fault visible from both endpoints) is not modelled here.
- **Thresholds are static.** No adaptive baselining; a GPU that idles hot still
  uses the same 90°C trip as one under load. Rate-based escalation
  (SBE/hr, replay/24h) reuses the existing `escalation-thresholds` mechanism
  rather than re-implementing it in the poller.
- **`XID_ERRORS` reports only the *last* code.** If two different Xids occur
  between scrapes, only the latest is visible in telemetry — the NVRM log path
  remains the complete Xid record. Telemetry is corroboration, not replacement.

---

## 15. Work breakdown (implementation order, TDD)

1. `tests/test_dcgm_poller.py` — write failing tests first (parse, normalize,
   each edge rule, state roundtrip, contract glue).
2. `dcgm_poller.py` — parser, BDF normalizer, edge engine, state I/O, emitter,
   CLI. Make tests green.
3. `examples/dcgm/gen_dcgm_synthetic.py` + paired `.prom` fixtures +
   `expected.dcgm.jsonl` golden.
4. `AGENT.md` — add the DCGM hot table + XID-delegation note.
5. `skills/dcgm-telemetry/` — `SKILL.md` + `references/`.
6. `examples/dcgm/validate_dcgm.py` — live end-to-end harness (gated).
7. Docs — README section + CLAUDE.md notes (poller, fixtures, gotchas).
8. `.gitignore` — add the poller's default dev state path so transient state is
   never committed.

Each step verifies against a concrete check (failing→passing tests for 1–2;
`validate_dcgm.py` green for 3–6; offline suite still hermetic throughout).
