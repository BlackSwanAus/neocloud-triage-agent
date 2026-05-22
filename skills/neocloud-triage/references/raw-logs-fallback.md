# Raw-log fallback procedures

Use these only when `report.ndjson` indicates the Tier-1 source for a family is missing or partial.

## Xid scan from raw kernel journal

```
artifact: logs/journal_kernel.ndjson
pattern : NVRM: Xid \(PCI:([0-9a-f:.]+)\): (\d+)
extract : { bdf: $1, code: $2 }
```

Combine with `critical-log-patterns` for surrounding context (assertion failed, RPC failed, etc.).

## SXid scan

```
artifact: logs/journal_kernel.ndjson, nvidia/xid_errors.txt
pattern : NVRM:\s*SXid\s*\(PCI:([^)]+)\):\s*(\d+)
extract : { fabric_bdf: $1, code: $2 }
```

Cross-check VFIO state in `hypervisor/vfio_bindings.txt` before classifying severity (see `xid-catalog` SXid rule).

## ECC scan

```
artifact: logs/dmesg.txt + logs/journal_kernel.ndjson
patterns: EDAC MC\d+: \d+ UE         → uncorrectable
          EDAC MC\d+: \d+ CE         → correctable, rate-classify
          Memory failure: 0x[0-9a-f]+:
```

If `hardware/edac_status.json` is present, prefer it over raw scan.

## PCIe AER scan

```
artifact: logs/journal_kernel.ndjson, logs/dmesg.txt
patterns: PCIe Bus Error: severity=Uncorrectable \(Fatal\)
          PCIe Bus Error: severity=Uncorrectable \(Non-Fatal\)
          PCIe Bus Error: severity=Corrected
```

Cross-reference with `hardware/pcie_aer_errors.json` if present.

## OOM / hard lockup / hung task

```
artifact: logs/journal_kernel.ndjson
patterns: Out of memory: Kill process
          Watchdog detected hard LOCKUP on cpu \d+
          BUG: soft lockup - CPU#\d+ stuck for \d+s
          INFO: task \S+:\d+ blocked for more than \d+ seconds
```

These are kernel/host concerns, not GPU. Findings family: `KERNEL_*`.

## Filesystem / disk

```
artifact: logs/journal_kernel.ndjson, hardware/smart_devices.txt
patterns: EXT4-fs error \(device
          XFS \(\S+\): Metadata CRC error
          Remounting filesystem read-only
          Sense Key\s*:\s*(Medium|Hardware) Error
```

## Container runtime

```
artifact: logs/journal_docker.ndjson, logs/journal_containerd.ndjson
patterns: failed to register layer
          layer does not exist
          manifest unknown
          nvidia-container-cli:.*nvml error
```

Container errors often look like GPU errors but aren't; correlate timestamp with workload events before escalating.

## Caps

Process at most:
- 50,000 lines per log file (head + tail; mid-truncation acceptable)
- 50 distinct events per family per archive

Above caps means dataset incomplete — note `truncated: true` in finding metadata.
