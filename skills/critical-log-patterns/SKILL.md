---
name: critical-log-patterns
description: Canonical regex patterns Hyperstack uses to detect critical kernel/syslog/journal events. Load only when the hyperstack-triage skill has determined that raw-log fallback is needed; provides families, regexes, and severities.
---

# Critical Log Patterns

These are the **exact** patterns embedded in the gather-info binary's `internal/triage.AnalyzeCriticalLogs`. Use them — do not invent. Family codes are stable identifiers used in dashboard fingerprinting.

## Rules of use

1. **Tier order.** If `triage/_data/critical_events.json` (or equivalent per family) exists, use it. These patterns are the **fallback** for when `report.ndjson` shows that triage data is missing or partial.
2. **Match into a family.** Free-form names break fingerprinting. Always emit `family: <STABLE_CODE>` from the tables.
3. **Case-insensitive.** All patterns assume `(?i)`.
4. **Multiline anchoring.** Patterns starting with `^` assume `(?m)` per-line matching.
5. **One finding per family per BDF.** Aggregate with `count` and `first_seen`/`last_seen`; do not emit one finding per matched line.
6. **Cap.** Stop at 50 distinct events per family per archive; mark `truncated: true`.
7. **VFIO suppression.** If `manifest.json` has `vfio_passthrough: true`, the family `NVIDIA_FABRIC_MANAGER_NOT_RUNNING` is suppressed.

## Common targets (load full catalog from `references/patterns.md`)

These cover the 80% case. For the rest, read `references/patterns.md`.

```
family                  | regex (CI)                                                  | severity
------------------------|-------------------------------------------------------------|---------
KERNEL_PANIC            | \bkernel panic\b|\bpanic - not syncing\b                    | critical
HARD_LOCKUP             | Watchdog detected hard LOCKUP on cpu \d+                    | critical
SOFT_LOCKUP             | BUG: soft lockup - CPU#\d+ stuck for \d+s                   | warning
HUNG_TASK               | INFO: task                                                  | warning
GPU_BUS_DOWN            | fallen off the bus                                          | critical
NVIDIA_ASSERT           | NVRM:.*(?:Assertion failed|Check failed)                    | critical
EDAC_UE                 | EDAC MC\d+: \d+ UE                                          | critical
EDAC_CE                 | EDAC MC\d+: \d+ CE                                          | warning *
MCE_HW_ERROR            | mce: \[Hardware Error\]                                     | critical
PCIE_AER_FATAL          | PCIe Bus Error: severity=Uncorrectable \(Fatal\)            | critical
PCIE_AER_NONFATAL       | PCIe Bus Error: severity=Uncorrectable \(Non-Fatal\)        | warning
PCIE_AER_CORRECTED      | PCIe Bus Error: severity=Corrected                          | info **
NVME_NOT_READY          | nvme nvme\d+: Device not ready; aborting                    | critical
NVME_CONTROLLER_DOWN    | nvme nvme\d+: controller is down                            | critical
EXT4_FS_ERROR           | EXT4-fs error \(device                                      | critical
XFS_CRC_ERROR           | XFS \(\S+\): Metadata CRC error                             | critical
FS_REMOUNT_RO           | Remounting filesystem read-only                             | critical
```

`*` `EDAC_CE` upgrades to `alert` at >50/day per `hyperstack-triage` escalation table.
`**` `PCIE_AER_CORRECTED` upgrades to `warning` at >20/24h, `alert` at >50/24h.

## BDF extraction

Many GPU/PCIe lines contain a bus:device.function. Extract with:

```
\b([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\b
```

Include the BDF in `evidence.bdf` on every PCIe/GPU finding. Without BDF, the dashboard can't dedupe across archives.

## Finding output

```
{
  "family": "<CODE_FROM_TABLE>",
  "severity": "<info|warning|alert|critical>",
  "count": <int>,
  "first_seen": "<ISO 8601>",
  "last_seen":  "<ISO 8601>",
  "bdf": "<optional>",
  "evidence": {
    "artifact": "<path>",
    "first_line_number": <int>,
    "verbatim": "<first matched line, sanitised>"
  }
}
```

If your matched verbatim line contains anything matching the secret regex in `references/secret-suppression.md`, replace before emitting.

## References

- `references/patterns.md` — full pattern catalog (GPU, NVMe, FS, CPU, PCIe, network, container, IPMI)
- `references/secret-suppression.md` — secret-class regexes to scrub from `verbatim` output
