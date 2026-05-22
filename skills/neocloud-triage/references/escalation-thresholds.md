# Escalation thresholds — full table

Rates and windows that upgrade or downgrade severity.

## Counts and rates

```
signal                        | metric                     | threshold (→severity)
------------------------------|----------------------------|----------------------
ECC SBE (correctable)         | events / 24h               | <10 info / 10-50 warning / >50 alert
ECC DBE (uncorrectable)       | any event                  | any → critical
PCIe AER corrected            | events / 24h               | <5 info / 5-20 warning / >20 alert
PCIe AER non-fatal            | any event                  | any → warning ; >3/24h → alert
PCIe AER fatal                | any event                  | any → critical
NVLink CRC retry              | events / 1h                | <100 info / 100-500 warning / >500 alert
Thermal warning               | junction temp °C           | <80 healthy / 80-85 warning / 85-95 alert / >95 critical
Thermal throttle              | events / 1h                | <5 info / 5-50 warning / >50 alert
Failed systemd units          | count                      | 0 healthy / 1-2 warning / 3+ alert
OOM kills                     | events / 24h               | 1 warning / >1 alert (host)
Soft lockup                   | events / 24h               | any → warning ; recurring → alert
Hard lockup                   | any                        | critical
Kernel panic                  | any                        | critical
File system remount RO        | any                        | critical
DCGM Health state             | == "Fail"                  | warning ; persistent >1h → alert
```

## Time windows for correlation

```
correlation                              | window
-----------------------------------------|--------
GPU Xid + SXid (same BDF)                | 10 s
PCIe AER + Xid 79                        | 5 min
Thermal threshold + Xid 46/109           | 5 min
OOM + container restart                  | 60 s
Same fingerprint, multiple tenants       | 24 h (cross-archive)
Same Xid across multiple GPUs same node  | 5 min  → upgrade to node-level
```

## Downgrade conditions

```
condition                                                          | effect
-------------------------------------------------------------------|-----------------
vfio_passthrough true + SXid only (no GPU Xid in 10s)              | downgrade to info
fabricmanager.service not running + vfio_passthrough true          | suppress finding
benign thermal recovery (peak temp returned to baseline in <5min)  | warning → info
known package update window (apt/dnf history shows event)          | mark "maintenance"
```

## Rate-of-change escalators

If the same warning persists across ≥3 consecutive archives from the same host with monotonically increasing count, upgrade to `alert` and tag `trend: increasing`. This is the predictive signal — surface it to the fleet-ml pipeline.
