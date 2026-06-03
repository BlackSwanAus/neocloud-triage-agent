# DCGM Edge & Threshold Rationale

The **canonical source of truth for threshold values is `dcgm_poller.py`** (the
`RULES` table). This file documents the reasoning so the numbers can be reviewed
and kept in sync. Changing a threshold means editing `dcgm_poller.py`; update
this file to match.

## Gauge thresholds (emit on below→above crossing)

| Metric | Threshold | Hysteresis | Why |
|---|---|---|---|
| `DCGM_FI_DEV_GPU_TEMP` | 90 °C | 2 °C | H100 begins HW thermal slowdown ~84–87 °C and shuts down ~92 °C. 90 °C is past managed throttling and into risk territory. Re-arm at <88 °C avoids flapping at the boundary. |
| `DCGM_FI_DEV_MEMORY_TEMP` | 95 °C | 2 °C | HBM3 runs hotter than the die; 95 °C is the practical alarm point for memory. |

## Counter edges (emit on increase)

No threshold — *any* increase is a real new occurrence and emits once. Rate-based
escalation (e.g. SBE >1000/hr, PCIe replay >50 total → upgrade severity) is the
job of `neocloud-triage/references/escalation-thresholds.md`, not the poller.

## Persistence gate (throttle)

| Metric | min_consecutive | Why |
|---|---|---|
| `DCGM_FI_DEV_CLOCK_THROTTLE_REASONS` | 3 polls | Momentary throttling during clock management is normal. Requiring the HW-fault bits (`HwSlowdown 0x8`, `SwThermal 0x20`, `HwThermal 0x40`, `HwPowerBrake 0x80` → mask `0xE8`) to persist 3 consecutive polls gates out transient blips. At a 15 s interval that is ~45 s of sustained throttle. |

## Counter-reset handling

dcgm-exporter or the driver can restart, resetting a counter to 0. The poller
detects `value < last` and re-baselines from the new value instead of computing a
spurious negative delta — so a restart never fabricates or swallows a fault.

## What is deliberately NOT thresholded

Utilization/capacity gauges (`GPU_UTIL`, `FB_USED/FREE`, clocks, PCIe
throughput) are **not** in the poller's `RULES` and never emit. They are
performance telemetry, not health faults; including them was explicitly out of
scope to keep the feed valid (low-noise). Add them only with a corresponding
threshold rule and test.
