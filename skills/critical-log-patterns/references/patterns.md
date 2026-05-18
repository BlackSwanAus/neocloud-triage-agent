# Full pattern catalog

All patterns case-insensitive. Source: `internal/triage` in gather-info binary.

## GPU / NVIDIA

```
KERNEL_PANIC                 \bkernel panic\b|\bpanic - not syncing\b                           critical
NVIDIA_ASSERT                NVRM:.*(?:Assertion failed|Check failed)                            critical
NVIDIA_RPC_FAIL              NVRM:.*rpcSendMessage failed                                        warning
NVIDIA_CONTAINER_CLI_ERROR   nvidia-container-cli:.*nvml error                                   warning
GPU_BUS_DOWN                 fallen off the bus                                                  critical
NVIDIA_DRIVER_WARN           WARNING: CPU: \d+.*at nvidia/                                       warning
NVRM_XID                     NVRM:\s*Xid\s*\(PCI:([0-9a-f:.]+)\):\s*(\d+)                        (resolve via xid-catalog)
NVRM_SXID                    NVRM:\s*SXid\s*\(PCI:([^)]+)\):\s*(\d+)                             (resolve via xid-catalog SXid)
```

## NVMe / SCSI / ATA

```
NVME_NOT_READY               nvme nvme\d+: Device not ready; aborting                            critical
NVME_CONTROLLER_DOWN         nvme nvme\d+: controller is down                                    critical
NVME_TIMEOUT_RESET           nvme nvme\d+: .*(?:timeout, reset controller|resetting controller)  warning
NVME_IO_ERROR                (?:I/O error, dev nvme\d+n\d+|nvme nvme\d+: I/O error)              warning
BLOCK_IO_ERROR               blk_update_request: I/O error, dev                                  warning
SCSI_MEDIUM_ERROR            Sense Key\s*:\s*Medium Error                                        warning
SCSI_HARDWARE_ERROR          Sense Key\s*:\s*Hardware Error                                      critical
ATA_LINK_DOWN                ata\d+: SATA link down                                              warning
ATA_FAILED_COMMAND           ata\d+\.\d+: failed command:                                        warning
ATA_COMRESET_FAIL            ata\d+(?:\.\d+)?: COMRESET failed                                   warning
ATA_HARD_RESET               ata\d+: hard resetting link                                         info
```

## Filesystem

```
EXT4_FS_ERROR                EXT4-fs error \(device                                              critical
XFS_CRC_ERROR                XFS \(\S+\): Metadata CRC error                                     critical
FS_REMOUNT_RO                Remounting filesystem read-only                                     critical
```

## Memory / ECC / MCE

```
MCE_HW_ERROR                 mce: \[Hardware Error\]                                             critical
HW_ERROR_FATAL               \{[^}]*\}\[Hardware Error\]:.*event severity: fatal                 critical
HW_ERROR_CORRECTED           \{[^}]*\}\[Hardware Error\]:.*event severity: (corrected|recoverable) info
EDAC_UE                      EDAC MC\d+: \d+ UE                                                  critical
EDAC_CE                      EDAC MC\d+: \d+ CE                                                  warning
MEMORY_FAILURE               Memory failure: 0x[0-9a-f]+:                                        warning
BERT_PREV_BOOT               BERT: Error records from previous boot                              warning
RAS_SOFT_OFFLINE             RAS: Soft-offlining pfn:                                            info
```

## CPU / Kernel

```
HARD_LOCKUP                  Watchdog detected hard LOCKUP on cpu \d+                            critical
SOFT_LOCKUP                  BUG: soft lockup - CPU#\d+ stuck for \d+s                           warning
HUNG_TASK                    INFO: task                                                          warning
RCU_STALL                    rcu:.*stall                                                         warning
CPU_THERMAL_THRESHOLD        CPU\d+: (?:Package|Core) temperature above threshold                warning
SEGFAULT                     \bsegfault\b                                                        info
BUG_CALL_TRACE               \bCall Trace:                                                       (context only — don't classify alone)
```

## PCIe

```
PCIE_AER_FATAL               PCIe Bus Error: severity=Uncorrectable \(Fatal\)                    critical
PCIE_AER_NONFATAL            PCIe Bus Error: severity=Uncorrectable \(Non-Fatal\)                warning
PCIE_AER_CORRECTED           PCIe Bus Error: severity=Corrected                                  info
PCIE_HOTPLUG_TIMEOUT         pcieport [0-9a-f:.]+: pciehp: Timeout on hotplug command            warning
```

## Network

```
NETDEV_WATCHDOG              NETDEV WATCHDOG: \S+ \(\S+\): transmit queue \d+ timed out          warning
```

## Container runtime

```
CONTAINER_LAYER_FAILURE      (failed to register layer|layer does not exist)                     warning
CONTAINER_MANIFEST_UNKNOWN   manifest unknown                                                    warning
```

## IPMI System Event Log (apply to `ipmi/sel_events.txt`)

Single regex; any match → family `IPMI_SEL_CRITICAL`, severity `critical`:

```
\b(uncorrectable|non-recoverable|upper critical|lower critical|predictive failure|state deasserted|failure detected|ierr|perr|serr|machine check|timer expired|thermal trip|bus fatal error|fatal nmi|drive fault|redundancy lost|memory scrub failed)\b
```

## BDF extractor helper

```
\b([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])\b
```

## Anchored helpers (set `(?m)` mode)

```
^Status:\s+(\S+)
^Default:\s+(\S+)\s+\(incoming\)
^Chain\s+(\S+)\s+\(policy\s+(\S+)
```

Used by firewall posture analysis — see `hyperstack-triage` for usage.
