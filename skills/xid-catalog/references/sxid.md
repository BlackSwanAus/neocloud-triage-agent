# SXid — NVSwitch fabric errors

SXid codes are emitted by NVSwitch (fabric controller), not GPUs. Their fingerprint is `SXid_` prefix or one of the `ROBUST_CHANNEL_*` / `NVLINK_*` symbolic names.

## Hot list

```
name                                  | severity | action
ROBUST_CHANNEL_NVLINK_TREX_ERROR      | critical | reset-gpu; NVLink5 workflow
NVLINK_NETIR_ERROR                    | critical | reset-gpu; contact support
NVLINK_PRIV_ERR                       | warning  | monitor
NVLINK_SECURE_CRYPTO_ERR              | critical | reset-gpu
NVLINK_MSE_ERROR                      | warning  | monitor
PBDMA_PUSHBUFFER_CRC_MISMATCH         | warning  | reset-gpu
GSP_RPC_TIMEOUT                       | critical | reset-gpu
GSP_ERROR                             | critical | reset-gpu
SEC2_HALT_ERROR                       | critical | reset-gpu
SEC_FAULT_ERROR                       | warning  | reset-gpu
PSHC_ZERO_LIFETIME                    | warning  | monitor
PSHC_DISENGAGED                       | warning  | monitor
CHANNEL_RETIREMENT_EVENT              | warning  | monitor
INFOROM_DRAM_RETIREMENT_EVENT         | info     | none
SMBPBI_TEST_MESSAGE_SILENT            | info     | none
```

## VFIO passthrough rule (critical)

When `manifest.json` shows `vfio_passthrough: true`:
- **SXid without a matching GPU Xid** within 10 seconds → fabric isolation working as designed. Do NOT escalate. Emit as `info` with note `"vfio_fabric_isolation"`.
- **SXid + matching GPU Xid** within 10 s on the same BDF → real fabric error. Use the more severe of the two.

## Never-RMA-on-SXid-alone

SXid alone never authorises RMA. Require a correlated GPU-side Xid (48, 64, 79, 95, 140, 171, 172) or a sustained high-rate event from EDAC. See `rma-decision` skill.

## Source

`internal/triage` SXid handling in the gather-info binary; symbolic names from `xidcatalog/catalog_generated.go`.
