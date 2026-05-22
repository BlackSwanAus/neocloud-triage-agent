---
name: rma-decision
description: Decide whether a finding qualifies for RMA. Use only after the neocloud-triage skill has produced classified findings; never invoke from raw evidence. Outputs a verdict and the rule that triggered it.
---

# RMA Decision

RMA is the most expensive recommendation this system makes. Wrong-side error costs:
- **False positive:** wasted hardware return, customer downtime, support credibility damage.
- **False negative:** running customer workload on degrading hardware, escalating failure.

The 2-signal rule is the discipline that keeps both error modes low.

## The 2-signal rule

Never recommend `rma-candidate` from one signal alone. Every RMA verdict must cite **two correlated signals** from distinct families.

Families counted as "distinct":
- `XID` (with code) — counts as one signal regardless of how many times it fires
- `ECC_CE` (rate-based)
- `ECC_UE` / `EDAC_UE`
- `PCIE_AER_FATAL` / `PCIE_AER_NONFATAL`
- `NVLINK_*`
- `SMART_*`
- `IPMI_SEL_CRITICAL`
- `THERMAL_*` (only counts if sustained, not transient)

Two events of the **same** family count as one signal.

## Canonical RMA verdicts

```
verdict             | meaning                                  | who acts
--------------------|------------------------------------------|---------------------
none                | no action                                | —
monitor             | re-check next archive, ≤7 days           | operator queue
investigate         | engineer review needed                   | support team
rma-candidate       | ship for RMA after engineer confirms     | hardware team
rma-urgent          | immediate workload migration + RMA       | on-call hardware
```

`rma-candidate` and above always require human approval — never apply autonomously.

## Decision tree

```
input: classified findings from neocloud-triage (post-escalation)

if any finding.severity == "critical":
    if any pair of distinct-family signals correlated within 24h:
        verdict = rma-candidate
        if (workload-impacting now OR uncontained_ecc OR PCIE_AER_FATAL):
            verdict = rma-urgent
    else:
        verdict = investigate    # one critical signal, no corroboration
elif any finding.severity == "alert":
    if any pair of distinct-family signals correlated within 7 days:
        verdict = investigate
    else:
        verdict = monitor
elif any finding.severity == "warning":
    if 3+ archives in 14 days show the same fingerprint:
        verdict = investigate    # persistent warning → escalate
    else:
        verdict = monitor
else:
    verdict = none
```

## Canonical 2-signal patterns

```
pattern                                                          | verdict
-----------------------------------------------------------------|----------------
Xid 48 (ECC DBE) + Xid 64 (DRAM remap fail)                      | rma-candidate
Xid 48 + EDAC_CE rate >50/day on same MC                         | rma-candidate
Xid 79 (bus down) + PCIE_AER_FATAL or PCIE_AER_NONFATAL >3/24h   | rma-candidate (seating)
Xid 95 (uncontained ECC) + kernel_tainted flag set               | rma-urgent
Xid 171/172 (UNCORRECTABLE_DRAM/SRAM) + any second signal        | rma-urgent
EDAC_UE + EDAC_CE on same MC                                     | rma-candidate
DCGM Health = Fail persistent >1h + any Xid >warning             | rma-candidate
NVLink CRC retry sustained + Xid 149 (NVLINK_NETIR)              | rma-candidate (NVLink5 workflow)
IPMI_SEL_CRITICAL + Xid {46,48,79,95,109,120}                    | rma-candidate
SMART {Reallocated_Sector,Pending_Sector} increasing + SCSI HW   | rma-candidate (storage)
```

## Single-signal — never RMA

```
single critical Xid (no corroboration)         → investigate
single PCIE_AER_FATAL (no second family)       → investigate
isolated thermal trip with recovery            → monitor
single EDAC_UE event on a new MC               → investigate (could be cosmic ray)
DCGM Health = Fail with no other signal        → investigate
```

## VFIO / NVSwitch exceptions

The following do not authorise RMA even if they look critical:

- SXid without a matching GPU Xid within 10 s on VFIO-passthrough hosts → fabric isolation working; no RMA.
- `nvidia-fabricmanager.service` not running on VFIO-passthrough host → expected; no finding.
- `nvidia-container-cli` errors when no GPU Xid present → workload/driver issue, not hardware.

See `xid-catalog` `references/sxid.md` for the VFIO logic.

## Cross-tenant escalator (when MCP available)

If `search_by_fingerprint` shows the same critical fingerprint from **≥2 distinct tenants** on the same `dmi.system_serial` within 24 h:

- Single-tenant verdict was `investigate` → upgrade to `rma-candidate` (the host, not the workload, is the issue)
- Add tag `multi-tenant-confirmed`, list tenant_count and serial in evidence.

This is the highest-confidence RMA pattern: hardware that fails for multiple independent tenants is unambiguously the hardware's fault.

## Output

```
{
  "verdict": "<none|monitor|investigate|rma-candidate|rma-urgent>",
  "rule": "<short identifier from the canonical patterns table, or 'single-signal' / 'no-correlation'>",
  "signals": [
    {"family": "...", "code_or_metric": "...", "evidence_ref": "<finding_id>"},
    {"family": "...", "code_or_metric": "...", "evidence_ref": "<finding_id>"}
  ],
  "correlation_window_seconds": <int>,
  "requires_human_approval": true,
  "notes": "<short string explaining edge cases>"
}
```

`requires_human_approval` is always `true` for `rma-candidate` / `rma-urgent`. The agent never marks an RMA as applied; only operators do.

## What is *not* in scope here

- Choosing the replacement part (operator decision).
- Scheduling the workload drain (operator/control-plane decision).
- Communicating with the customer (templated by the dashboard, not the agent).

This skill ends at the verdict.
