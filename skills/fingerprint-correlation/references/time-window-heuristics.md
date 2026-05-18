# Time-Window Heuristics for Fingerprint Correlation

Extended decision matrix derived from Meta Llama-3 operational wisdom and neocloud RMA patterns.

## GPU Fault Correlation

| Signal Pair | Time Window | Inference | Confidence |
|-------------|------------|-----------|------------|
| GPU Xid + kernel dmesg error | ±5 s | Xid is the GPU fault; dmesg is a symptom | high |
| GPU Xid + app CUDA error | ±2 s | GPU error caused app to fail | high |
| GPU Xid + app timeout | ±5 s | GPU hang/reset triggered timeout | high |
| GPU Xid + NCCL collective timeout | ±5 s | One GPU dropped from collective | high |
| GPU Xid + no app log entry | >10 s | GPU recovered silently; workload may not know | medium |

## Thermal Fault Correlation

| Pattern | Time Window | Inference | Confidence |
|---------|------------|-----------|------------|
| DCGM thermal throttle → Xid 94 (power mgmt) | T-30 to T+2 s | Thermal triggered power management fault | high |
| DCGM thermal violation → GPU reset | T-5 to T+10 s | Thermal recovery triggered reset | high |
| IPMI SEL temp sensor crossing threshold → Xid | ±15 s | Sensor reading preceded fault | medium |
| THERMAL_VIOLATIONS on 2+ devices same blade | 24 h | Shared cooling issue (ambient, PSU) | high |
| Same THERMAL_VIOLATIONS on 3+ hosts, same rack | 24 h | Rack-level cooling failure | high |

## Memory Error Correlation

| Pattern | Time Window | Inference | Confidence |
|---------|------------|-----------|------------|
| DCGM ECC SBE rate spike → Xid 30 (mem corruption) | T-30 to T+5 s | Memory errors triggered GPU reset | high |
| EDAC_CE (host DRAM) + DCGM mem error (vRAM) | T-60 to T+30 s | Shared power rail degradation | medium |
| RETIRED_PAGES increment + Xid 48 (DBE) | T-120 to T+30 s | GPU firmware retiring bad pages after error | high |
| Same ECC SBE pattern on 2+ GPUs same host | ±120 s | Shared memory bus or power integrity | medium |

## Multi-Tenant Colocation

| Pattern | Time Window | Inference | Confidence |
|---------|------------|-----------|------------|
| Same issue_fingerprint from 2 tenants, same `dmi.system_serial` | 24 h | Infra-side fault; affects multiple workloads | critical |
| Same issue_fingerprint from 3+ tenants, same serial | 24 h | Definite hardware issue; upgrade RMA confidence | critical |
| Thermal spike → GPU Xid (same host, different tenants) | ±5 s | Thermal event affected collocated workloads | high |
| Non-overlapping tenant uptime, same Xid pattern | 7 days | Workload-independent; hardware fault | high |

**Action:** Multi-tenant colocation with 2+ distinct tenants on same serial triggers rma-decision escalator; hand verdict upward regardless of single-archive severity.

## Novelty Detection

| Pattern | Fleet Window | Inference | Confidence |
|---------|---------------|-----------|------------|
| issue_fingerprint never seen in past 30 days | fleet-wide | Novel signal; first-time presentation | medium |
| issue_fingerprint ≥5 occurrences in 7 days | fleet-wide | Emergent issue; rate accelerating | medium |
| issue_fingerprint ≥10 occurrences in 7 days | fleet-wide | Systemic problem; may be firmware/config | low-automation |
| issue_fingerprint suddenly ≥2x normal rate | 7 days vs. baseline | Possible new condition (workload pattern, cluster config) | medium |

**Action:** If novel and count ≥5 in 7 days, lower automation confidence and escalate to human operators. Do not auto-RMA.

## Recurrence and Persistence

| Pattern | Lookback | Inference | Confidence |
|---------|----------|-----------|------------|
| Same issue_fingerprint on same host, 1 prior in 30 d | 30 days | Recurrence; hardware degrading | high |
| Same issue_fingerprint on same host, ≥2 priors in 30 d | 30 days | Persistent failure; escalate RMA | high |
| Same issue_fingerprint on same host, ≥1 per week for 4 weeks | 30 days | Chronic issue; recommend replace | high |
| Same issue_fingerprint on same host, gaps >7 days | 30 days | Sporadic; may be load-dependent | medium |

**Action:** Recurrence on same host after 7+ days quiescence may justify re-RMA if other signals appear.

## Thermal Clustering

| Pattern | Time Window | Shared Infrastructure | Inference | Confidence |
|---------|------------|----------------------|-----------|------------|
| 2 hosts, same Xid pattern, same PDU/PSU group | 24 h | Power supply | Shared PSU degradation | high |
| 3+ hosts, same Xid pattern, same blade/chassis | 24 h | Cooling loop, power distribution | Shared environmental fault | high |
| Same thermal threshold violation, different GPUs | 24 h | Ambient temperature or airflow | Rack-level cooling issue | medium |
| IPMI SEL fans throttling + GPU Xid on 2+ hosts | 24 h | Cooling subsystem | CRAC/chiller failure likely | high |

**Action:** If thermal cluster detected, recommend checking shared infrastructure (PSU, cooling) before RMA-ing individual nodes.

## Constraints and Edge Cases

### Overlapping time windows

If two signal pairs both match (e.g., Xid + dmesg within ±5s AND Xid + app timeout within ±5s), report both but note they may be causally linked (single underlying GPU fault, multiple symptom traces).

### Sparse fleet correlation

If fleet has <5 archives total in past 7 days, novelty detection confidence drops; treat novel signals as "under-sampled, not truly rare."

### Workload influence

- Multi-tenant colocation WITHOUT overlapping workload runtimes → **stronger** infra signal (workload-independent)
- Multi-tenant colocation WITH overlapping workload runtimes → **weaker** signal (could be workload interaction); escalate to human review

### False positives from isolation

- SXid on VFIO-passthrough host without corresponding GPU Xid within ±10s → **fabric isolation is working**; downgrade to info
- See `xid-catalog` references for VFIO edge cases

## References

- **Meta Llama-3 GPU Reliability Paper** (arxiv:2407.10635): ±5s window for GPU causation, 24h for thermal clustering
- **research-neocloud-ops.md** Section 4.4: Time-window heuristics from neocloud operations
- **NVIDIA DCGM Metrics**: Field identifiers and event timing guarantees (https://docs.nvidia.com/datacenter/dcgm/latest/api-reference/field-identifiers.html)
