# Hyperstack Archive Structure and Artifact Map

Standard layout for `support-YYYY-MM-DD.tar.gz` produced by Hyperstack gather-info.

## Top-level files

```
manifest.json              GPU inventory, VFIO/NVSwitch topology, collector version
report.ndjson              Per-collector execution status (success/missing/partial)
README.md                  (optional) human summary
```

## Triage pre-classified findings (Tier-1; read first)

```
triage/
├── _data/
│   ├── summary.json          Aggregate severity verdict (use as source of truth)
│   ├── xid_events.json       Parsed Xid events (distinct-family only)
│   ├── ecc_events.json       ECC error events (SBE vs UBE by memory controller)
│   ├── thermal_anomalies.json Thermal violations and throttle events
│   ├── power_events.json     Power rail and OCP events
│   ├── nvlink_errors.json    NVLink CRC and bandwidth errors
│   ├── pcie_aer_events.json  PCIe Advanced Error Reporting events
│   └── critical_events.json  Kernel panic, hard lockup, OOM killer hits
└── analysis.log            (optional) triage run log
```

## Raw logs (fallback if Tier-1 missing)

```
kernel.log                 Kernel dmesg (fallback if triage missing)
dmesg.log                  Alternative kernel log filename
nvidia-debug.log           NVIDIA driver debug log (optional)
system.log                 syslog or journalctl -u nvidia-* (system-wide)
```

## GPU and host state snapshots

```
nvidia-smi.txt             nvidia-smi -q output (snapshot)
nvidia-smi-xml.xml         nvidia-smi -q -x (full XML state)
dcgm-diagnostics.json      DCGM diag -r 3 (full system validation)
dcgm-metrics.csv           DCGM field dump (time-series, optional)
dcgm-health-check.json     DCGM health state query result
```

## Orchestration state (if Kubernetes)

```
kubernetes/
├── nodes.yaml             kubectl describe nodes (all nodes)
├── pods.yaml              kubectl describe pods (all namespaces)
├── events.yaml            kubectl get events (all namespaces, with timestamps)
├── node-feature-discovery.yaml  NFD labels
└── gpu-plugin.log         nvidia-device-plugin or gpu-device-plugin logs
```

## Orchestration state (if OpenStack)

```
openstack/
├── nova-compute.log       nova-compute service log from hypervisor host
├── instance-metadata.json Instance UUID, flavor, etc.
├── cyborg-resources.json  Cyborg accelerator resource state
└── ironic-inspection.json Ironic node inspection data (bare-metal)
```

## Hardware and firmware state

```
lspci-vvv.txt              lspci -vvv (PCIe device tree, link speeds)
dmidecode.txt              dmidecode (DMI/SMBIOS data; system UUID, serial)
ipmi-sel-dump.txt          IPMI System Event Log (thermal, power, fan events)
ipmi-fru-data.txt          IPMI Field Replaceable Unit data (board info)
ethtool-dump.txt           ethtool -i <iface> (NIC firmware, link status)
```

## Storage and workload context (optional)

```
docker-ps-all.txt          docker ps -a (workload names, image tags)
nvme-smart.txt             nvme smart-log (NVMe health, reallocated sectors)
df-h.txt                   df -h (filesystem usage, mount points)
ps-aux.txt                 ps aux (running processes at collection time)
```

## File → Triage Family Mapping

| Triage Family | Primary Raw File | Fallback | JSON Path |
|---------------|------------------|----------|-----------|
| XID_EVENTS | triage/_data/xid_events.json | kernel.log | $.events[*].code |
| ECC_EVENTS | triage/_data/ecc_events.json | kernel.log | $.events[*].type |
| THERMAL_ANOMALIES | triage/_data/thermal_anomalies.json | dcgm-metrics.csv | $.events[*].violation |
| POWER_EVENTS | triage/_data/power_events.json | kernel.log | $.events[*].rail |
| NVLINK_ERRORS | triage/_data/nvlink_errors.json | dcgm-metrics.csv | $.errors[*].link_id |
| PCIE_AER | triage/_data/pcie_aer_events.json | kernel.log | $.events[*].severity |
| CRITICAL_LOGS | triage/_data/critical_events.json | kernel.log, system.log | $.events[*].type |
| GPU_STATE_SNAPSHOT | nvidia-smi-xml.xml, dcgm-diagnostics.json | nvidia-smi.txt | $.gpus[0].* |

## Evidence citation examples

**From Tier-1 (xid_events.json):**
```
artifact: "support-2026-05-18.tar.gz/triage/_data/xid_events.json"
json_path: "$.events[3]"
verbatim: {"code": 48, "bdf": "0001:00:00.0", "timestamp": "2026-05-18T14:05:30Z"}
```

**From raw kernel.log (fallback):**
```
artifact: "support-2026-05-18.tar.gz/kernel.log"
line: 142
verbatim: "NVIDIA GPU 0: Xid (PCI ID 1234:abcd): 48, ECC DBE detected"
```

**From DCGM metrics CSV:**
```
artifact: "support-2026-05-18.tar.gz/dcgm-metrics.csv"
line_range: [10, 20]
anchor_line: 15
note: "ECC_DBE_VOL field shows sustained >0 from 14:05:00Z to 14:10:00Z"
```

## report.ndjson status codes

Each line is a JSON object:
```json
{"artifact": "kernel.log", "status": "success", "size_bytes": 123456}
{"artifact": "triage/_data/xid_events.json", "status": "success"}
{"artifact": "dcgm-metrics.csv", "status": "partial", "reason": "collection timeout at 5 minutes"}
{"artifact": "nvidia-smi-xml.xml", "status": "missing", "reason": "driver not loaded"}
```

**Status values:**
- `success` — artifact present, complete
- `partial` — artifact present but truncated/incomplete (note the reason)
- `missing` — artifact not collected (note the reason)

Before citing an artifact, check `report.ndjson` for its status. If `partial` or `missing`, cite the report.ndjson entry and adjust hedging language.
