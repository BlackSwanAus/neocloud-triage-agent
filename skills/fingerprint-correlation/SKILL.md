---
name: fingerprint-correlation
description: Use when per-archive triage (via hyperstack-triage skill) has produced ≥warning findings. Correlates findings across archives via MCP dashboard queries to detect recurrence, multi-tenant colocations, and novel emergent issues. Returns correlation signals that feed rma-decision and ai-finding-format skills.
---

# Fingerprint Correlation

Single-archive findings are ambiguous: a GPU Xid on one host could be an isolated hardware defect, a widespread firmware bug, or a false positive. Correlation across archives reveals the true scope.

## When to invoke

Load this skill **after** hyperstack-triage has produced findings. Specifically:

- per-archive severity ≥ **warning** (do not query on healthy/info)
- MCP dashboard tools available (`search_by_fingerprint`, `find_similar_archives`, `recent_archives`)
- target: inject correlation_signals into the evidence that flows to rma-decision and ai-finding-format

Do not invoke without a fingerprint from the current archive's issues.

## Core routine

For each finding from the per-archive triage (severity ≥warning):

1. **Fetch the `issue_fingerprint`** from the triage output; do not invent strings.
2. **Query `search_by_fingerprint(issue_fingerprint, since=<30 days ago>)`** to find prior occurrences.
3. **Classify the result:**
   - 1 prior on same host in 30 days → **recurrence**: upgrade severity tag `recurring`
   - ≥2 distinct tenants on same `dmi.system_serial` within 24 h → **multi-tenant colocator**: cite serial, count tenants, tag `multi-tenant-confirmed` (hand to rma-decision escalator)
   - ≥5 fleet-wide in 7 days, first seen now → **novel emergent**: tag `novel`, lower automation confidence
   - ≥10 fleet-wide in 7 days → **endemic**: likely systemic issue (firmware, config); may reduce per-host severity

4. **For multi-tenant colocations only:** call `recent_archives(host_id=<host>, hours=72)` to find precursor archives on the same host before/after the current archive. Look for thermal/power clustering.

5. **Encode time windows per the Meta Llama-3 operational heuristics:**
   - GPU fault + app timeout: ±5 seconds → causally linked
   - Thermal cluster (same power rail/blade): ≤24 hours → batch failure likely
   - Memory error recovery: 30–60 seconds recovery window

6. **Forbidden behaviors:**
   - Do not query without a fingerprint or archive_id.
   - Do not infer archive/tenant counts beyond what MCP returned.
   - Do not name other tenants; cite only the serial and count.
   - Do not assume precursor event causation; only flag temporal proximity for human review.

## Output

Append `correlation_signals` to the evidence object for each finding:

```json
{
  "finding_id": "...",
  "severity": "warning|alert|critical",
  "correlation_signals": [
    {
      "type": "recurrence",
      "confidence": "high",
      "evidence": "1 prior occurrence on hyperstack-gpu-01 on 2026-05-10",
      "recommendation": "upgrade severity to alert"
    },
    {
      "type": "multi_tenant_colocation",
      "confidence": "critical",
      "dmi_system_serial": "SYS001234",
      "tenant_count": 3,
      "time_window_hours": 24,
      "recommendation": "escalate to rma-decision with multi-tenant-confirmed tag"
    },
    {
      "type": "novel_emergent",
      "confidence": "medium",
      "fleet_occurrences_7d": 6,
      "first_seen_timestamp": "2026-05-18T14:05:30Z",
      "recommendation": "monitor; defer automation until pattern stabilizes"
    },
    {
      "type": "thermal_cluster",
      "confidence": "high",
      "cluster_count": 4,
      "time_window_hours": 24,
      "shared_infrastructure": "shared-psu-group-7",
      "recommendation": "investigate power rail or ambient cooling"
    }
  ]
}
```

Fields:
- `type` — `recurrence`, `multi_tenant_colocation`, `novel_emergent`, `thermal_cluster`, or custom
- `confidence` — `high`, `medium`, or `low`; correlates to automation gating in downstream skills
- `time_window_*` — actual window from MCP result or heuristic
- `recommendation` — short actionable for the next skill (rma-decision or ai-finding-format)

## Time-window heuristics (from Meta Llama-3 operations)

| Pattern | Window | Inference |
|---------|--------|-----------|
| GPU Xid + app timeout | ±5 s | GPU fault caused timeout |
| Thermal violation + Xid | T-30 to T+2 s | Thermal preceded GPU error |
| ECC soft-error recovery | 30–60 s | Memory error triggered GPU reset |
| Same fingerprint, same host | 30 days | Recurrence; hardware degradation likely |
| Same fingerprint, same serial, different tenants | 24 hours | Infra-side fault; multiple workloads affected |
| Thermal cluster (same PSU/blade) | 24 hours | Shared environmental fault |
| Novel fingerprint (fleet-wide) | 7 days | If ≥5 occurrences in 7 days: emergent issue |

See `references/time-window-heuristics.md` for extended decision matrix.

## Integration with other skills

- **Input:** Finding with `issue_fingerprint` from hyperstack-triage
- **Depends on:** MCP dashboard (`search_by_fingerprint`, `find_similar_archives`, `recent_archives`)
- **Output to:** rma-decision (correlation_signals feed the 2-signal rule), ai-finding-format (to populate evidence and recommendation fields)

Workflow:
```
hyperstack-triage (per-archive) 
  → fingerprint-correlation (cross-archive query + signal generation)
    → rma-decision (use correlation_signals for 2-signal verdict)
    → ai-finding-format (embed signals in finding JSON for dashboard write-back)
```

## Privacy contract (critical)

The MCP server enforces per-tenant isolation at the SQL layer. This skill must **not** reason about archives or counts outside what the MCP returned.

- Query result says "3 tenants on serial SYS001": cite exactly 3; never infer 4.
- Query result returns 0 matches: do not assume hidden matches; only report what was returned.
- Never attempt to name other tenants; cite serial and count only.

The agent's claim authority is the MCP result, not training data or external knowledge.

## Common pitfalls

1. **Querying without a fingerprint:** Every call must have an `issue_fingerprint` from the current archive's findings.
2. **Inferring causation from time proximity:** Thermal spike + GPU Xid ±5s is correlated, not causal; flag for human review.
3. **Treating "not found" as "not present":** If `search_by_fingerprint` returns 0 matches, this is a novel signal. Do not assume it's truly rare; the MCP viewer may lack access to other archives.
4. **Misclassifying thermal clusters:** Multi-GPU same Xid on one node is not always thermal; check IPMI SEL for power rail events, not just temperature.
5. **Over-automating novel issues:** If a fingerprint is new fleet-wide, lower confidence and hand to human operators. Do not escalate RMA.

## References

- **rma-decision** — consumes correlation_signals; applies the 2-signal rule
- **hyperstack-triage** — produces per-archive findings with fingerprints
- **ai-finding-format** — formats correlated findings for dashboard write-back
- **research-neocloud-ops.md** — Section 4 (Cross-archive correlation patterns), Section 5.3 (thermal clustering heuristics)
- `references/time-window-heuristics.md` — extended time-window lookup table
- `references/multi-tenant-detection.md` — full colocation detection algorithm
