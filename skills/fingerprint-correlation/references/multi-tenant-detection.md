# Multi-Tenant Colocation Detection Algorithm

The highest-confidence RMA pattern: hardware failing for multiple independent tenants.

## Detection flow

```
input: issue_fingerprint from current archive finding

step 1: query MCP search_by_fingerprint(issue_fingerprint, since=<24 hours ago>)
step 2: for each result, extract dmi.system_serial
step 3: group results by dmi.system_serial
step 4: for each serial, check tenant_count from MCP result
step 5: if any serial has ≥2 distinct tenants within 24 h → multi_tenant_colocation signal
```

## Evidence format

```json
{
  "type": "multi_tenant_colocation",
  "confidence": "critical",
  "dmi_system_serial": "SYS001234",
  "tenant_count": 3,
  "occurrences": [
    {
      "archive_id": "550e8400-e29b-41d4-a716-446655440000",
      "hostname": "hyperstack-gpu-01.lab",
      "tenant_id": "customer-a",
      "uploaded_at": "2026-05-18T14:00:00Z"
    },
    {
      "archive_id": "660e8400-e29b-41d4-a716-446655440001",
      "hostname": "hyperstack-gpu-01.lab",
      "tenant_id": "customer-b",
      "uploaded_at": "2026-05-18T14:15:00Z"
    },
    {
      "archive_id": "770e8400-e29b-41d4-a716-446655440002",
      "hostname": "hyperstack-gpu-01.lab",
      "tenant_id": "customer-c",
      "uploaded_at": "2026-05-18T15:30:00Z"
    }
  ],
  "time_window_hours": 24,
  "shared_infrastructure": "dmi.system_serial=SYS001234",
  "privacy_contract": "tenant_id names omitted in downstream finding; only serial and count cited",
  "recommendation": "escalate to rma-decision with multi-tenant-confirmed tag; hardware-level RMA justified"
}
```

### Privacy constraint

Citation format:
```
3 distinct tenants on dmi.system_serial SYS001234 within 24 hours.
Archives: 550e8400-..., 660e8400-..., 770e8400-...
```

**Never name** other tenants in the finding text. Cite serial and count only. The MCP server enforces isolation; the skill respects it.

## Precursor detection (thermal clustering)

For multi-tenant colocation signals, optionally call `recent_archives(host_id=<host>, hours=72)` to check for precursor events:

```
Archive 1 (T-24h, tenant-a): DCGM THERMAL_VIOLATIONS detected
Archive 2 (T-0h, tenant-a): GPU Xid 94 (power mgmt)
Archive 3 (T-0h, tenant-b): GPU Xid 94
Archive 4 (T+4h, tenant-c): GPU Xid 94
```

Interpretation: Shared thermal event may have triggered cascading failures. Escalate to "investigate shared infrastructure" rather than per-device RMA.

## Decision tree for multi-tenant signal

| Tenant Count | Time Window | Single-Tenant Verdict | Multi-Tenant Action |
|--------------|-------------|----------------------|---------------------|
| 1 | N/A | investigate | none (use single-archive verdict) |
| 2 | 24 h | investigate | **upgrade to rma-candidate** |
| 2 | 24 h | monitor | **upgrade to investigate** |
| 3+ | 24 h | any | **upgrade to rma-candidate** + escalate to on-call |
| 2 | 7 days | warning | **upgrade to investigate** |
| 3+ | 7 days | any | **upgrade to investigate** |

The multi-tenant-confirmed tag overrides the single-archive verdict; it is the strongest RMA evidence.

## Caveats

### Non-overlapping workload runtimes

If tenant-a's archive is from 14:00 and tenant-b's is from 20:00 (>6h apart), and there's no evidence they ran simultaneously:

- Multi-tenant signal still valid (same hardware, same issue within 24h)
- But workload-independence is lower; escalate to human review
- Possible that tenant-a's workload left hardware degraded for tenant-b

### Shared-tenant accounts

Some neoclouds use a single "system" tenant or "admin" tenant for orchestration. If MCP lists same tenant twice:

- Filter duplicates; count only distinct tenant IDs
- If all occurrences are the same tenant on the same host: fall back to single-archive verdict

### Colocation by design

Some platforms intentionally collocate workloads (e.g., Kubernetes multi-tenant namespace). Multi-tenant colocation is **still significant** because:

- Different workloads have different behaviors
- Hardware fault affects all collocated workloads
- Demonstrates infrastructure-side, not workload-side, issue

Do **not** suppress multi-tenant signals for designed colocation.

## Integration with rma-decision

When rma-decision receives a finding with `correlation_signals` containing `multi_tenant_colocation`:

```
if correlation_signals.type == "multi_tenant_colocation":
  verdict = rma-candidate  # override single-signal rule
  tag = "multi-tenant-confirmed"
  cite = f"{signal.tenant_count} tenants on {signal.dmi_system_serial}"
```

This is the "cross-tenant escalator" from rma-decision skill Section 7.

## Common mistakes

1. **Counting the same tenant twice**: Filter by distinct tenant_id before counting.
2. **Ignoring time window**: ≥2 tenants within 24h is the rule; beyond 24h drops to "investigate" (not RMA).
3. **Naming tenants in the output**: Cite serial and count; never include tenant names in findings.
4. **Assuming causation**: Colocation is correlation, not causation. Hardware may be the cause, but don't assume it caused both failures; let rma-decision apply the business logic.
5. **Forgetting to call recent_archives**: For cluster-level faults (thermal, power), precursor detection helps distinguish per-device vs. infrastructure issues.

## References

- **rma-decision** skill: Section 7 (Cross-tenant escalator)
- **research-neocloud-ops.md**: Section 4.1 (Physical host identity)
- **MCP dashboard spec**: `search_by_fingerprint` and `recent_archives` tool definitions
