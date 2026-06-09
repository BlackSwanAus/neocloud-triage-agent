---
name: ai-finding-format
description: The canonical JSON schema for triage agent findings. Use only after evidence-citation and fingerprint-correlation have completed. Emits deterministic, dashboard-ingested JSON for the ai_findings table.
---

# AI Finding Format

The triage agent's structured output. Every finding object produced by the agent must conform to `references/ai-finding.schema.json` before write-back to the dashboard.

## Why This Matters

Prose-style findings (`"GPU went down"`) cannot be parsed by the dashboard for fingerprinting, correlation, or RMA eligibility. Structured JSON fixes this: the same finding shape enables repetition detection, tenant isolation, and vendor escalation workflows.

## Required Top-Level Fields

Every finding must include:

- **`archive_id`** (UUID) — which support archive this finding came from
- **`family`** (string, enum) — stable code from canonical families: `XID`, `ECC_CE`, `ECC_UE`, `EDAC_CE`, `EDAC_UE`, `PCIE_AER_FATAL`, `PCIE_AER_NONFATAL`, `NVLINK_*`, `THERMAL_*`, `KERNEL_PANIC`, `HARD_LOCKUP`, `GPU_BUS_DOWN`, `IPMI_SEL_CRITICAL`, `SMART_*`, etc. Never invent.
- **`code`** (int for Xid; string for named families) — numeric XID or symbolic name
- **`severity`** (enum: `info`, `warning`, `alert`, `critical`) — from `neocloud-triage` escalation table, not raw defaults
- **`confidence`** (enum: `low`, `medium`, `high`) — trust in the evidence
- **`action`** (enum: `none`, `monitor`, `restart-app`, `reset-gpu`, `reboot-node`, `escalate-for-review`, `contact-support`, `tune-workload`) — canonical verb from `xid-catalog`
- **`evidence`** (array of objects) — each cites an artifact path + line number with `{artifact, line, verbatim}`
- **`count`** (int) — how many matching raw events underlie this finding

## Optional Blocks

**Correlation block** (present only if `fingerprint-correlation` ran):
- `prior_occurrences` — count from MCP search_by_fingerprint
- `multi_tenant_same_host` — boolean, true if ≥2 tenants on same dmi.system_serial
- `novelty_30d` — boolean, true if not seen fleet-wide in 30 days

**RMA verdict block** (present only if `rma-decision` ran):
- `verdict` (enum: `none`, `monitor`, `investigate`, `rma-candidate`, `rma-urgent`) — never apply autonomously
- `signals` — array of the two distinct-family signals that triggered the verdict
- `requires_human_approval` — always true for `rma-candidate` / `rma-urgent`

**Provenance block** (REQUIRED for every finding):
- `model_version` — Claude model ID, e.g. `claude-sonnet-4-6`
- `prompt_hash` — SHA256 of system prompt + skills loaded (enables eval reproducibility)
- `skills_loaded` — array of skill names + versions, matching actual directory names: `["neocloud-triage/v1.0", "xid-catalog/v2.1", "evidence-citation/v1.0"]`
- `mcp_tools_called` — count by tool name: `{"search_by_fingerprint": 3, "preview_artifact": 7}`
- `created_at` — ISO 8601 timestamp

**Severity audit block** (if severity differs from catalog default):
- `severity_upgraded_from` / `severity_downgraded_from` — the reason (e.g. `rate-breach-50-per-day`)
- `change_reason` — short identifier

**Optional fields**:
- `bdf` (string) — PCIe/GPU only, e.g. `0004:04:00.0`
- `issue_fingerprint` — copied from dashboard issue record if citing an existing issue

## Validation Rules

1. **No free-form families.** Family must be one of the canonicals; invent nothing.
2. **Action verb must match xid-catalog.** Verb is a routing signal downstream.
3. **Evidence without artifact is forbidden.** Every citation must have artifact + line.
4. **RMA verdict only from rma-decision.** Never author your own verdict.
5. **Severity conforms to neocloud-triage table.** Use escalation rules; don't override.
6. **Binary RMA gating.** Verdict is `none` | `monitor` | `investigate` | `rma-candidate` | `rma-urgent`. Not `awaiting-review` or custom values.

## Worked Examples

See `references/examples.md`:
- *Example A:* Single-archive Xid 48 with one evidence ref, no RMA verdict
- *Example B:* Multi-tenant correlated Xid 79 + PCIE_AER_FATAL with rma-candidate verdict

## Complete Schema

Full JSON Schema (draft 2020-12): `references/ai-finding.schema.json`  
$id: `https://neocloud.example/schemas/ai-finding/v1`

Use this for dashboard validator and agent pre-flight checks.
