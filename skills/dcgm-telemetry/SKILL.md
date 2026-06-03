---
name: dcgm-telemetry
description: Classify NVIDIA DCGM-exporter telemetry signals (DCGM_FI_DEV_* metrics). Returns Neocloud family, severity, and action for ECC/XID/thermal/throttle/NVLink/PCIe telemetry edges. Use when a DCGM_FI_DEV_* line appears; do NOT guess thresholds from memory.
---

# DCGM-Exporter Telemetry Catalog (lookup-only)

DCGM telemetry arrives **pre-filtered by the DCGM poller** — each signal is a real
edge event (counter increase, threshold crossing, persistent throttle), not a raw
sample. Your job is to *classify* it, not to re-derive whether it's notable.

## Resolution order

1. **Metric in the DCGM hot table in AGENT.md?** Use it. Stop.
2. **`DCGM_FI_DEV_XID_ERRORS`?** The value is the *last Xid code*. Emit
   `family: XID, code: <value>` and resolve severity/action from the **Xid** hot
   table (not this one).
3. **Otherwise** `Read references/dcgm-fields.tsv` and match the metric name.
4. **No match anywhere?** `family: UNKNOWN_DCGM`, severity `warning`, action
   `escalate-for-review`. Never invent.

## BDF normalization

dcgm-exporter's `pci_bus_id` label has an 8-hex PCI domain
(`00000000:18:00.0`). Take the low 4 hex of the domain → canonical
`0000:18:00.0`. This lets telemetry findings dedupe against Xid/log findings on
the same device.

## Field semantics

- **Counters** (`ECC_*_VOL_TOTAL`, `PCIE_REPLAY_COUNTER`, `NVLINK_*_ERROR_*`,
  `THERMAL_VIOLATION`, `POWER_VIOLATION`, `RETIRED_*`, `ROW_REMAP_FAILURE`) —
  the poller emits only on an increase. Treat any received signal as a real new
  occurrence.
- **Gauges** (`GPU_TEMP`, `MEMORY_TEMP`) — the poller emits only on a
  below→above threshold crossing (90°C / 95°C), so a received signal means the
  GPU is over limit *now*.
- **`XID_ERRORS`** — value is a code, not a count. Delegate to the Xid catalog.
- **`CLOCK_THROTTLE_REASONS`** — bitmask; the poller emits only after the
  hardware-fault bits persist for 3+ polls. A received signal means *sustained*
  HW throttling, not a momentary blip.

## Neocloud-specific rules

- **Single-signal rule.** A `critical` DCGM finding authorises "investigate",
  **not** RMA. RMA needs the `rma-decision` 2-signal test. A DCGM DBE plus an
  NVRM-logged Xid 48 on the same BDF is exactly the independent corroboration
  that rule wants.
- **Severity is Neocloud's, not NVIDIA's.** Already reflects our overrides.
- Action verbs: `none` `monitor` `restart-app` `reset-gpu` `reboot-node`
  `escalate-for-review` `contact-support`.

## Output contract

```
{
  "family": "DCGM_ECC_DBE",
  "severity": "critical",
  "action": "reset-gpu",
  "bdf": "0000:18:00.0",
  "evidence": {"verbatim": "<raw DCGM line, secret-scrubbed>"}
}
```

For XID-via-DCGM, also include `"code": <value>` and use `"family": "XID"`.

## Source

Curated `references/dcgm-fields.tsv` is the Neocloud override layer (severity
bumps, action verbs, RMA thresholds). `references/source-dcgm-fields.tsv` is the
canonical metric list extracted from a `dcgm-exporter` default-counter CSV.
Threshold *values* are owned canonically by `dcgm_poller.py`; see
`references/thresholds.md` for rationale. Field meanings cross-reference
`skills/evidence-citation/references/dcgm-fields.md`.
