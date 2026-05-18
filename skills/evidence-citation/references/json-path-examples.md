# JSONPath Examples for Structured Evidence

When citing Tier-1 structured data (xid_events.json, ecc_events.json, etc.), use JSONPath notation to pinpoint the exact field.

## JSONPath Syntax (JSONPath 0.9.9 / RFC 9535)

| Notation | Meaning |
|----------|---------|
| `$` | Root object |
| `.key` | Object property |
| `[n]` | Array index (0-based) |
| `[*]` | All array elements |
| `[?(@.property == value)]` | Filter: elements where property == value |
| `..key` | Recursive descent (all nested `key` fields) |

## Examples by Family

### xid_events.json

Structure:
```json
{
  "events": [
    {
      "index": 0,
      "code": 48,
      "name": "ECC_DBE",
      "bdf": "0001:00:00.0",
      "timestamp": "2026-05-18T14:05:30Z",
      "severity": "critical",
      "count": 1
    }
  ],
  "total_events": 3
}
```

**Citation examples:**

```
json_path: "$.events[0]"
verbatim: {"code": 48, "name": "ECC_DBE", "bdf": "0001:00:00.0", "timestamp": "2026-05-18T14:05:30Z"}

json_path: "$.events[0].code"
verbatim: 48

json_path: "$.events[?(@.severity == 'critical')]"
verbatim: [{"code": 48, ...}, {"code": 79, ...}]  // all critical-severity events

json_path: "$.total_events"
verbatim: 3
```

### ecc_events.json

Structure:
```json
{
  "memory_controllers": [
    {
      "mc_id": 0,
      "events": [
        {
          "type": "SBE",  // Single-Bit Error or "UBE" (Uncorrectable)
          "count": 47,
          "rate_per_hour": 3.2,
          "first_seen": "2026-05-18T13:00:00Z",
          "last_seen": "2026-05-18T14:05:30Z"
        }
      ]
    }
  ]
}
```

**Citation examples:**

```
json_path: "$.memory_controllers[0].events[0]"
verbatim: {"type": "SBE", "count": 47, "rate_per_hour": 3.2}

json_path: "$.memory_controllers[0].events[?(@.type == 'UBE')]"
verbatim: {"type": "UBE", "count": 0}  // no UBE on MC 0

json_path: "$..events[?(@.rate_per_hour > 5)]"
verbatim: [{"type": "SBE", "rate_per_hour": 7.8}]  // all high-rate events across all MCs
```

### thermal_anomalies.json

Structure:
```json
{
  "violations": [
    {
      "timestamp": "2026-05-18T13:45:00Z",
      "gpu_id": 0,
      "type": "throttle",  // "throttle" or "thermal_shutdown"
      "max_temp_celsius": 78.5,
      "duration_seconds": 12,
      "reason": "sustained high load"
    }
  ]
}
```

**Citation examples:**

```
json_path: "$.violations[0]"
verbatim: {"timestamp": "2026-05-18T13:45:00Z", "gpu_id": 0, "type": "throttle", "max_temp_celsius": 78.5}

json_path: "$.violations[?(@.type == 'thermal_shutdown')]"
verbatim: []  // no thermal shutdown events in this archive

json_path: "$..max_temp_celsius"
verbatim: [78.5, 79.2, 75.3]  // all max temps across violations
```

### nvlink_errors.json

Structure:
```json
{
  "per_link_stats": [
    {
      "link_id": "0->1",  // GPU 0 to GPU 1
      "crc_flit_errors": 0,
      "crc_data_errors": 0,
      "replay_errors": 0,
      "bandwidth_gb_s": 890.5,
      "expected_gb_s": 900.0,
      "utilization_pct": 98.9,
      "last_error_timestamp": null
    }
  ]
}
```

**Citation examples:**

```
json_path: "$.per_link_stats[0]"
verbatim: {"link_id": "0->1", "crc_flit_errors": 0, "bandwidth_gb_s": 890.5}

json_path: "$.per_link_stats[?(@.crc_flit_errors > 0)]"
verbatim: []  // no links with CRC errors in this archive

json_path: "$..bandwidth_gb_s"
verbatim: [890.5, 892.1, 891.8]  // all link bandwidths
```

### critical_events.json

Structure:
```json
{
  "kernel_events": [
    {
      "type": "KERNEL_PANIC",  // or "HARD_LOCKUP", "SOFT_LOCKUP", etc.
      "timestamp": "2026-05-18T14:05:30Z",
      "cpu_id": null,
      "error_message": "Kernel panic - not syncing: Fatal exception in interrupt"
    }
  ]
}
```

**Citation examples:**

```
json_path: "$.kernel_events[?(@.type == 'KERNEL_PANIC')]"
verbatim: {"type": "KERNEL_PANIC", "timestamp": "...", "error_message": "..."}

json_path: "$.kernel_events[0].type"
verbatim: "KERNEL_PANIC"
```

## Writing evidence blocks with JSONPath

**Template:**
```json
{
  "evidence": {
    "artifact": "support-2026-05-18.tar.gz/triage/_data/xid_events.json",
    "json_path": "$.events[?(@.severity == 'critical')]",
    "verbatim": [/* matching elements from above query */],
    "note": "Found 2 critical Xid events (codes 48, 79) in archive"
  }
}
```

**When to use JSONPath vs. line numbers:**
- Use JSONPath when citing structured Tier-1 data (triage/_data/*.json).
- Use line numbers when citing raw text logs (kernel.log, dmesg.log, etc.).
- Never mix: pick one per evidence block.

## Escaping special characters

If your JSONPath contains special characters (quotes, backslashes), escape them:
```
json_path: "$.events[?(@.bdf == \"0001:00:00.0\")]"
```

Or use single-quoted JSONPath if your JSON library supports it:
```
json_path: "$.events[?(@.error_message =~ /timeout/i)]"  // regex filter
```
