---
name: evidence-citation
description: Every triage claim must cite a specific artifact path + line number (or JSON path for structured data). Load on every triage session. Encodes citation rules, multi-line handling, JSON paths, partial/redacted evidence, and forbidden behaviors (unsourced claims, paraphrases that change meaning, claims without artifact existence checks).
---

# Evidence Citation Discipline

This is the **anti-hallucination foundation** for triage findings. Every fact asserted must be grounded in artifact evidence with exact path and line references. No unsourced claims survive RMA disputes.

## Citation format (canonical)

For **text artifacts** (dmesg, logs, JSON):

```json
{
  "evidence": {
    "artifact": "support-2026-05-18.tar.gz/kernel-dmesg.log",
    "line": 142,
    "verbatim": "NVIDIA GPU 0: Xid (PCI ID 1234:abcd): 48, ECC DBE detected"
  }
}
```

For **JSON/NDJSON artifacts**:

```json
{
  "evidence": {
    "artifact": "support-2026-05-18.tar.gz/triage/_data/xid_events.json",
    "json_path": "$.events[3]",
    "verbatim": {"code": 48, "bdf": "0001:00:00.0", "timestamp": "2026-05-18T14:05:30Z"}
  }
}
```

For **multi-line** (e.g., context around a line):

```json
{
  "evidence": {
    "artifact": "...",
    "line_range": [140, 145],
    "anchor_line": 142,
    "verbatim": "... context before ...\nNVIDIA GPU 0: Xid 48, ECC DBE detected\n... context after ..."
  }
}
```

For **partial/redacted** evidence (artifact damaged or truncated):

```json
{
  "evidence": {
    "artifact": "...",
    "line": 456,
    "verbatim": "[REDACTED]/data/model.safetensors",
    "note": "artifact truncated; line count incomplete"
  }
}
```

## Rules (mandatory)

1. **Every finding must have an evidence block.** No exceptions. No claim is true until you cite it.

2. **Artifact must exist.** Before writing a finding, confirm the artifact path in `report.ndjson` under `artifacts:` or as a file in `triage/_data/`. If missing, cite `report.ndjson` and note the collection failure.

3. **Line numbers are 1-indexed.** Match the tool's output (most text tools use 1-based).

4. **Direct quoting over paraphrase.** When possible, include verbatim text in the evidence block. If you paraphrase, flag it: `"paraphrased": true` and store the original line in a separate `original_line` field.

5. **JSON path over line number.** Structured data (DCGM JSON, Kubernetes Event objects) must cite `json_path` (JSONPath format `$.key[0].subkey`), not a line number. Line numbers are fragile for JSON.

6. **Cross-archive claims require `search_by_fingerprint`.** If you claim "this failure pattern occurred on three hosts," you must invoke the dashboard MCP's `search_by_fingerprint` tool. Never invent cross-archive claims without proof.

7. **Hedging language for partial evidence.** If the evidence is incomplete (e.g., journal was rotated, collection timed out), write: "Possible <X> based on <limited signal> (see evidence.note)."

8. **Secret suppression.** Before emitting verbatim text, check `references/secret-suppression.md`. Redact API keys, tokens, credentials, PII.

## Forbidden behaviors

- ❌ Claims without citations (e.g., "GPU error detected" with no evidence block).
- ❌ Paraphrasing that changes meaning (e.g., changing "occasional timeout" to "frequent timeout").
- ❌ Citations to artifacts not in `report.ndjson` (phantoms).
- ❌ Citing `triage/_data/` without first checking if the triage collector succeeded (see `report.ndjson` status).
- ❌ Unsourced "training memory" claims (DCGM field meanings, Xid codes, thermal thresholds). Use `xid-catalog` and `references/dcgm-fields.md`.

## Hyperstack artifact paths

Common paths; read `references/artifact-map.md` for the full list:

- `manifest.json` — GPU inventory, VFIO topology, collector version
- `report.ndjson` — per-collector status (success/missing/partial)
- `triage/_data/summary.json` — pre-classified findings (Tier-1 source)
- `triage/_data/xid_events.json` — parsed Xid events (distinct-family only; use `xid-catalog`)
- `triage/_data/ecc_events.json` — ECC error events (SBE vs UBE)
- `triage/_data/thermal_anomalies.json` — thermal violations
- `triage/_data/nvlink_errors.json` — NVLink fabric errors
- `dmesg.log` or `kernel.log` — kernel messages (fallback if triage missing)
- `dcgm-diagnostics.json` — DCGM full diagnostic dump

If the artifact is not listed, it is either missing or unstandardized. Halt and consult the ops team.

## Evidence output checklist

Before emitting a finding:

- [ ] Artifact path matches `report.ndjson` exactly (no typos, case-sensitive).
- [ ] Line or JSON path points to the exact location of the claim.
- [ ] Verbatim text is included (sanitised for secrets).
- [ ] If multi-artifact, each artifact in evidence array is distinct-family.
- [ ] If cross-archive, `search_by_fingerprint` was invoked and results included.
- [ ] If paraphrased, original line cited and `paraphrased: true` set.
- [ ] If partial, `note` explains why (truncation, rotation, collection failure).

## References

- `references/dcgm-fields.md` — DCGM field IDs and meanings (GPU_UTIL, FB_USED, ECC_ERRORS, NVLINK_BANDWIDTH, RETIRED_PAGES, etc.)
- `references/artifact-map.md` — Hyperstack archive structure; triage family → raw-file mapping
- `references/secret-suppression.md` — PII/credential regex patterns to redact before emitting verbatim
- `references/json-path-examples.md` — JSONPath syntax for xid_events.json, ecc_events.json, thermal_anomalies.json
