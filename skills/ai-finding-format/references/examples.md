# Worked Examples: AI Finding Format

## Example A: Single-Archive Xid 48 Finding (No RMA Verdict)

**Scenario:** Archive `550e8400-e29b-41d4-a716-446655440000` contains a single ECC DBE event (Xid 48) on GPU 0. No RMA decision has been made yet (rma-decision skill not invoked, or additional signal needed for 2-signal rule).

**Raw Evidence:**
- Source artifact: `logs/kernel.log`, line 1234
- Log line: `[12345.678901] NVRM: Xid (PCI:0004:04:00): 48, GPU has fallen off the bus.`
- GPU BDF: `0004:04:00.0`
- Confidence: high (direct kernel log citation)

**Finding JSON:**

```json
{
  "archive_id": "550e8400-e29b-41d4-a716-446655440000",
  "family": "XID",
  "code": 48,
  "severity": "critical",
  "confidence": "high",
  "action": "reset-gpu",
  "evidence": [
    {
      "artifact": "logs/kernel.log",
      "line": 1234,
      "verbatim": "[12345.678901] NVRM: Xid (PCI:0004:04:00): 48, GPU has fallen off the bus."
    }
  ],
  "count": 1,
  "bdf": "0004:04:00.0",
  "provenance": {
    "model_version": "claude-sonnet-4-6",
    "prompt_hash": "abc123def456abc123def456abc123def456abc123def456abc123def456ab",
    "skills_loaded": [
      "neocloud-triage/v1.0",
      "xid-catalog/v2.1",
      "evidence-citation/v1.0"
    ],
    "mcp_tools_called": {
      "preview_artifact": 1
    },
    "created_at": "2026-05-18T14:32:45Z"
  }
}
```

**Key points:**
- No `rma_verdict` block (rma-decision has not yet run, or single signal insufficient)
- No `correlation` block (fingerprint-correlation not yet invoked)
- Severity `critical` per xid-catalog: Xid 48 is always critical
- Action verb `reset-gpu` from xid-catalog's canonical actions
- Evidence array has exactly one citation; `verbatim` preserves the matched line
- Provenance records which Claude model, which skills, and when this finding was created

---

## Example B: Multi-Tenant Correlated Finding with RMA Verdict

**Scenario:** Archive `660e8400-e29b-41d4-a716-446655440001` (hostname: `neocloud-gpu-02.lab`) shows both:
1. Xid 79 (GPU Fallen Off Bus) at 2026-05-18T14:05:30Z
2. PCIE_AER_FATAL error at 2026-05-18T14:05:35Z (5 seconds later)

Fingerprint-correlation ran and found:
- 3 prior occurrences of this fingerprint (on different dates)
- 2 distinct tenants hit the same fingerprint on the same `dmi.system_serial` within 24 hours
- Not seen elsewhere in the past 30 days (relative novelty)

RMA-decision ran and determined this qualifies for `rma-candidate` (2-signal rule: Xid 79 + PCIE_AER_FATAL, distinct families, correlated within 24h).

**Raw Evidence:**
- Xid 79: source `logs/kernel.log`, line 2450, timestamp 2026-05-18T14:05:30Z
- PCIe AER Fatal: source `logs/kernel.log`, line 2455, timestamp 2026-05-18T14:05:35Z

**Finding JSON:**

```json
{
  "archive_id": "660e8400-e29b-41d4-a716-446655440001",
  "family": "XID",
  "code": 79,
  "severity": "critical",
  "confidence": "high",
  "action": "reboot-node",
  "evidence": [
    {
      "artifact": "logs/kernel.log",
      "line": 2450,
      "verbatim": "[54321.123456] NVRM: Xid (PCI:0004:04:00): 79, GPU Fallen Off Bus"
    },
    {
      "artifact": "logs/kernel.log",
      "line": 2455,
      "verbatim": "[54321.128456] PCIe Bus Error: severity=Uncorrectable (Fatal) (PCI:0004:04:00)"
    }
  ],
  "count": 1,
  "bdf": "0004:04:00.0",
  "issue_fingerprint": "pcie:0004:04:00:bus-down-with-fatal-aer",
  "correlation": {
    "prior_occurrences": 3,
    "multi_tenant_same_host": true,
    "novelty_30d": true
  },
  "rma_verdict": {
    "verdict": "rma-candidate",
    "signals": [
      {
        "family": "XID",
        "code_or_metric": "79",
        "evidence_ref": "finding_0_xid_79"
      },
      {
        "family": "PCIE_AER_FATAL",
        "code_or_metric": "Uncorrectable Fatal",
        "evidence_ref": "finding_1_pcie_aer"
      }
    ],
    "requires_human_approval": true
  },
  "provenance": {
    "model_version": "claude-sonnet-4-6",
    "prompt_hash": "def456abc123def456abc123def456abc123def456abc123def456abc123def4",
    "skills_loaded": [
      "neocloud-triage/v1.0",
      "xid-catalog/v2.1",
      "evidence-citation/v1.0",
      "fingerprint-correlation/v1.2",
      "rma-decision/v1.0"
    ],
    "mcp_tools_called": {
      "get_archive": 1,
      "list_issues": 2,
      "preview_artifact": 4,
      "search_by_fingerprint": 1,
      "find_similar_archives": 1
    },
    "created_at": "2026-05-18T14:35:20Z"
  }
}
```

**Key points:**
- Evidence array cites both the Xid 79 and the PCIE_AER_FATAL lines (distinct families, same window)
- Action verb `reboot-node` from xid-catalog for Xid 79 with suspected PCIe/seating issue
- `correlation` block populated by fingerprint-correlation:
  - `prior_occurrences: 3` — MCP search found 3 earlier archives with this fingerprint
  - `multi_tenant_same_host: true` — ≥2 distinct tenants on same physical host (high confidence this is hardware, not tenant workload issue)
  - `novelty_30d: true` — this fingerprint has not been seen elsewhere in fleet within 30 days (higher urgency)
- `rma_verdict` block populated by rma-decision:
  - `verdict: rma-candidate` — escalate to hardware team for RMA decision (with human approval required)
  - `signals` array lists the two distinct families that triggered the verdict
  - `requires_human_approval: true` — operator must manually approve RMA; agent cannot apply
- `skills_loaded` shows all 5 skills were invoked (triage → evidence-citation → fingerprint-correlation → rma-decision)
- `mcp_tools_called` documents the MCP calls made during this analysis (for audit and reproducibility)

---

## Validation Checklist

For both examples, verify:
- ✓ All required top-level fields present
- ✓ `family` is from the canonical enum (not free-form)
- ✓ `severity` conforms to `neocloud-triage` escalation table
- ✓ `action` verb is from xid-catalog's canonical list
- ✓ Every evidence citation has `artifact` + `line` (no missing paths)
- ✓ `rma_verdict` block present only if rma-decision ran
- ✓ `correlation` block present only if fingerprint-correlation ran
- ✓ `provenance` block always present with all required fields
- ✓ `prompt_hash` is valid SHA256 hex (64 chars, lowercase)
- ✓ `created_at` is valid ISO 8601 datetime
- ✓ No additional properties beyond schema definition
- ✓ All enums use exact canonical values

Both findings pass schema validation against `ai-finding.schema.json`.
