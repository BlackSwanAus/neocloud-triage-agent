---
name: neocloud-triage
description: Methodology for triaging a Neocloud gather-info archive. Defines the strict artifact read-order and the severity escalation table. Load whenever you start analysing an archive_id; controls workflow, not lookup.
---

# Neocloud Triage Workflow

Triage is **read-order disciplined**: structured signals supersede raw logs. Cracking open a journal file before checking pre-classified findings is the most common rookie error and the source of most false RMAs.

## Read order (do not skip steps)

1. **`manifest.json`** — GPU inventory, VFIO/NVSwitch topology, collector version, machine_class.
2. **`report.ndjson`** — which collectors succeeded, which artifacts are missing/partial. Tells you which downstream sources are trustworthy.
3. **`triage/_data/summary.json`** — already-classified findings. **If present, this is the source of truth.** Treat as Tier-1 evidence.
4. **`triage/_data/<family>.json`** — per-family parsed events (`xid_events`, `thermal_anomalies`, `power_events`, `ecc_events`, `memory_errors`, `nvlink_errors`). Tier-1 evidence.
5. **Raw logs (only if Tier-1 gap)** — see `references/artifact-map.md` for the canonical layout and which raw file backs each triage family.

If you find yourself at step 5 without first confirming the artifact is missing at step 2, stop and re-read `report.ndjson`.

## Classification (the only severities Neocloud uses)

```
healthy   no critical/warning findings; ECC SBE < 10/day; no Xid in 30 days
warning   1 signal in {Xid, ECC, AER, NVLink degraded}; <2-signal RMA threshold
alert     2+ correlated signals OR sustained rate breach OR DCGM Health=Fail >1h
critical  Xid {46,48,62,64,79,95,109,120,140,143,158,166,167,169,171,172} present,
          or uncontained ECC, or PCIe AER Fatal, or kernel hard LOCKUP / panic
```

`alert` and `critical` both trigger immediate operator notification; only `critical` may invoke automated reset. RMA is a **separate decision** — invoke the `rma-decision` skill.

## Escalation rules (per-archive)

- Single `info` Xid (e.g. 63 DRAM_RETIREMENT) → log, do not escalate.
- Same `warning` Xid ≥2× in 24h on same BDF → upgrade to `alert`.
- `EDAC_CE` rate > 50/day → upgrade to `alert`.
- `EDAC_CE` + `EDAC_UE` on the same MC → `critical`.
- Any `critical` Xid + matching SXid within 10 s → `critical` (genuine fabric error, not VFIO isolation).
- `vfio_passthrough: true` + SXid without GPU Xid within 10 s → downgrade to `info` (`vfio_fabric_isolation`). This is the most common false-positive source — see `xid-catalog`'s `references/sxid.md`.

## Cross-archive escalation (when MCP tools available)

If the dashboard MCP is attached, after producing the per-archive verdict:

1. Call `search_by_fingerprint` for each `warning`-or-higher finding.
2. If ≥2 distinct tenants have the same fingerprint on the same `dmi.system_serial` within 24 h → upgrade host-side severity to `alert`, flag as `infra-suspect`.
3. If the fingerprint is novel (not seen in past 30 days fleet-wide) → tag `novel`, lower automation confidence regardless of severity.

## Workflow

```
manifest.json → inventory
report.ndjson → known-good vs known-missing
  └── triage/_data/summary.json present?
        yes → classify from Tier-1 only
        no  → fall through to triage/_data/<family>.json
              └── empty? → references/raw-logs-fallback.md
classify per the severity table above
apply escalation rules
if MCP available: search_by_fingerprint for each ≥warning finding
emit findings using ai-finding-format skill
```

## Output discipline

- Every finding cites at least one `artifact_path` + `line` (use the `evidence-citation` skill).
- Action verb must be canonical (see `xid-catalog`).
- Never recommend RMA from this skill — defer to `rma-decision`.
- If a finding upgrades or downgrades from a default, set `severity_changed_reason`.

## Neocloud-specific tuning

- Multi-GPU same Xid on 3+ devices on one node → **node-level** finding, not per-GPU. Tag `node_level: true`. Likely thermal/power, not GPU defect.
- `nvidia-fabricmanager.service` not running on a VFIO-passthrough host is expected; never a finding.
- Workload-aware: if `docker_ps_all.txt` shows `vllm-*` and you see CUDA OOM correlated with model-load timestamps, recommend `tune-workload` (action verb) not `reset-gpu`.

## References

- `references/artifact-map.md` — full bundle layout, family → raw-file mapping
- `references/raw-logs-fallback.md` — what to grep when Tier-1 is missing
- `references/escalation-thresholds.md` — full rate/window tables
