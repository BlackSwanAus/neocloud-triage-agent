# DCGM Field Identifiers

Reference for DCGM metrics used in Hyperstack findings. Do not invent field meanings; use these canonical definitions from NVIDIA documentation.

**Source:** https://docs.nvidia.com/datacenter/dcgm/latest/api-reference/field-identifiers.html

## GPU Health Metrics

| Field | ID | Meaning | Severity Signal | RMA Threshold |
|-------|----|---------|--------------------|----------|
| GPU_UTIL | 1001 | GPU streaming multiprocessor utilization (%) | Low util during high-power = hang | N/A |
| FB_USED | 1002 | GPU framebuffer (VRAM) used (MB) | OOM risk >95% | N/A |
| FB_FREE | 1003 | GPU framebuffer free (MB) | — | N/A |
| SM_OCCUPANCY | 1004 | Occupancy of active kernel (fraction) | Low occ + high power = inefficiency | N/A |
| SM_CLOCK | 1005 | SM clock rate (MHz) | Throttling if dropping mid-workload | N/A |
| MEMORY_CLOCK | 1006 | Memory clock rate (MHz) | Throttling if dropping | N/A |
| POWER_DRAW | 1008 | Instantaneous power draw (watts) | >95% limit = thermal risk | N/A |
| POWER_LIMIT | 1009 | Power limit setting (watts) | — | N/A |
| PCIE_RX_THROUGHPUT | 1011 | PCIe RX bandwidth (MB/s) | Sustained low = link degradation | Investigate if <50% expected |
| PCIE_TX_THROUGHPUT | 1012 | PCIe TX bandwidth (MB/s) | Same as RX | Investigate if <50% expected |
| PCIE_REPLAY_COUNTER | 1013 | PCIe replay errors (cumulative) | >50 total = electrical issue | RMA if + Xid 79 |
| NVLINK_CRC_FLIT_ERR | 1050 | NVLink flow control error count (per-link) | >10/sec = quality degradation | RMA if + Xid 149 |
| NVLINK_CRC_DATA_ERR | 1051 | NVLink data error count (per-link) | Same as flit | Same as flit |
| NVLINK_BANDWIDTH | 1052 | Per-link throughput (GB/s) | <50% expected = link degraded | Investigate + check link speed |
| RETIRED_PAGES | 1087 | GPU memory pages soft-retired (count) | >0 significant; >10 serious | >20 = RMA candidate |
| ECC_ERRORS_AGGREGATE | 1089 | Total ECC errors (SBE + DBE, cumulative) | >1000/hr SBE = monitor; DBE = critical | DBE >0 = RMA candidate (needs 2-signal) |
| ECC_SBE_VOL | 1090 | Single-bit errors (SBE) per minute | >100/min = marginal memory | N/A (unless persistent trend) |
| ECC_DBE_VOL | 1091 | Double-bit errors (DBE) per minute | >0 = immediate alert | >0 = RMA candidate |
| THERMAL_VIOLATIONS | 1093 | Thermal throttle events (count) | 1+ during workload = risk | Sustained = investigate |

## Container/Workload Metrics

| Field | ID | Meaning |
|-------|----|---------| 
| GPU_INSTANCE_ID | 1208 | MIG/vGPU instance ID (per container) |
| PROCESS_NAME | 1304 | Process using GPU (e.g., vllm, triton) |
| PROCESS_MEMORY_GPU | 1305 | GPU memory allocated to process (MB) |

## DCGM Health State

**Health** field (query via DCGM API):
- `Healthy` — all subsystem checks pass; <10 SBE/hr; no recent Xid
- `Degraded` — minor issues (thermal throttle, high SBE rate)
- `Unhealthy` — DBE detected or sustained critical errors
- `Fail` — unrecoverable (Xid 45, 48, 79, 95) or RETIRED_PAGES > 20

If DCGM Health = **Fail** for >1 hour, escalate to RMA decision tree.

## Notes

- **SBE rate:** Baseline <10/hour is normal. >50/hour for >1 week suggests memory degradation; >1000/hour = RMA candidate (needs corroborating signal).
- **Retired pages:** Firmware-soft-retired memory due to SBE clustering. Hyperstack RMA threshold: >20. See `rma-decision` skill.
- **NVLink:** H100 and B200 use NVLink5 (900 GB/s per link). Gen3/Gen4 degradation visible via bandwidth drop or CRC error spike.
- **Thermal:** H100 max die temp ~85°C. Sustained >80°C during light load indicates cooling failure.

## Cross-references

- DCGM Metrics API: https://docs.nvidia.com/datacenter/dcgm/latest/api-reference/field-identifiers.html
- NVIDIA GPU Operator health checks: https://github.com/NVIDIA/gpu-operator#gpu-operator-with-dcgm-metrics
