---
name: xid-catalog
description: Look up NVIDIA Xid/SXid GPU error codes. Returns canonical name, severity, and Neocloud action policy. Use whenever a numeric Xid code or SXid name appears in artifacts; do NOT guess from training memory.
---

# Xid / SXid Catalog (lookup-only)

For every Xid code or SXid name encountered, resolve it with this skill instead of recalling from memory. NVIDIA's catalog drifts; Neocloud overrides drift faster.

## Resolution order

1. **Code in the hot table below?** Use it. Stop.
2. **Otherwise** `Read references/codes.tsv` and grep for the code.
3. **Code 154?** Read `references/xid-154.md` — its severity depends on the `recovery_action` field, not the code.
4. **SXid (NVSwitch fabric)?** Read `references/sxid.md`. SXid alone is never RMA.
5. **No match anywhere?** Treat as `UNKNOWN_XID`, severity `warning`, action `escalate-for-review`. Never invent.

## Hot table (covers ~80% of seen codes)

```
code|name|severity|action
13  |GR Exception                |warning |restart-app; cuda-gdb if recurring
31  |MMU Fault                   |warning |restart-app; check bounds access
46  |GPU Timeout                 |critical|reset-gpu; support if recurring
48  |ECC DBE                     |critical|reset-gpu; RMA candidate (needs 2nd signal)
63  |DRAM Retirement             |info    |none
64  |DRAM Remap Failure          |critical|reset-gpu; RMA candidate
79  |GPU Fallen Off Bus          |critical|reboot-node; check PCIe seating/power
92  |Excessive SBE Rate          |warning |monitor; escalate if persistent
95  |Uncontained ECC             |critical|reset-gpu; RMA candidate
109 |Context Switch Timeout      |critical|reset-gpu; contact support
119 |GSP RPC Timeout             |critical|reset-gpu; contact support
120 |GSP Error                   |critical|reset-gpu; contact support
149 |NVLINK NETIR Error          |critical|reset-gpu; follow NVLink5 workflow
154 |Recovery Action Changed     |varies  |see references/xid-154.md
```

## Field semantics

- `severity` — Neocloud severity, **not** NVIDIA's. Already accounts for our overrides.
- `action` — verb-prefixed canonical action. Use the exact verb in your finding output so the dashboard can route.
- Action verbs: `none` `monitor` `restart-app` `reset-gpu` `reboot-node` `escalate-for-review` `contact-support`.

## Neocloud-specific rules

- **Single-signal rule.** A `critical` severity here authorises "investigate", **not** RMA. RMA requires the `rma-decision` skill's 2-signal test.
- **VFIO exception.** When `manifest.json` shows `vfio_passthrough: true`, an SXid without a matching GPU Xid within 10 s is fabric isolation working — do not escalate. See `references/sxid.md`.
- **NVRM Fabric Manager not running.** Expected when NVSwitch is VFIO-passthrough. Not a finding.

## Output contract

When emitting an Xid finding:

```
{
  "family": "XID",
  "code": <int>,
  "name": "<canonical from catalog>",
  "severity": "<from catalog or escalation rule>",
  "action": "<canonical verb>",
  "bdf": "<from log line>",
  "evidence": {"artifact": "<path>", "line": <int>, "verbatim": "<sanitised>"}
}
```

If you upgraded the severity (e.g. `92` → `critical` because of >50/day rate), set `severity_upgraded_from` to the catalog default and `upgrade_reason` to the trigger.

## Source

Catalog is generated from `customers/vm-troubleshooting/internal/triage/xidcatalog/catalog_generated.go` in `NexGenCloud/hyperstack-support-scripts`. When NVIDIA publishes new codes, the in-binary catalog updates; re-export to `references/codes.tsv`.
