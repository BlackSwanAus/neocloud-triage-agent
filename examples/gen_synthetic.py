#!/usr/bin/env python3
"""
Synthetic signal-feed generator for the Hyperstack triage agent.

Emits a deterministic mix of:
  - Xid events (known + unknown codes)
  - Kernel/log patterns (matching critical-log-patterns regexes)
  - Manifest context flips (VFIO on/off to exercise suppression rules)
  - RMA scenarios (paired signals on same BDF — should pass 2-signal test)
  - Suppression scenarios (SXid under VFIO — should drop)
  - Secret-bearing lines (should be scrubbed in `verbatim`)

Outputs:
  feed.synthetic.txt        — agent input (SIGNAL/MANIFEST/SHUTDOWN blocks)
  expected.synthetic.jsonl  — golden findings (one JSON per signal_id)

Usage:
  python gen_synthetic.py [--seed N] [--scenarios all|smoke|rma|vfio|unknown]
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Catalogs (mirrors of /skills references — kept tiny to make goldens hand-readable)
# ---------------------------------------------------------------------------

XIDS: dict[int, tuple[str, str, str]] = {
    # code: (canonical_name, severity, action)
    13:  ("GR_EXCEPTION",        "warning",  "restart-app"),
    31:  ("MMU_ERR_FLT",         "warning",  "restart-app"),
    46:  ("GPU_TIMEOUT",         "critical", "reset-gpu"),
    48:  ("ECC_DBE",             "critical", "reset-gpu"),
    63:  ("DRAM_RETIREMENT",     "info",     "none"),
    64:  ("DRAM_FAIL",            "critical", "reset-gpu"),
    79:  ("FALLEN_OFF_BUS",      "critical", "reboot-node"),
    92:  ("EXCESSIVE_SBE",       "warning",  "monitor"),
    95:  ("UNCONTAINED_ECC",     "critical", "reset-gpu"),
    119: ("GSP_RPC_TIMEOUT",     "critical", "reset-gpu"),
    149: ("NVLINK_NETIR",        "critical", "reset-gpu"),
}

LOG_FAMILIES: dict[str, tuple[str, str]] = {
    # family: (template, severity)
    "KERNEL_PANIC":         ("Kernel panic - not syncing: VFS: Unable to mount root", "critical"),
    "HARD_LOCKUP":          ("Watchdog detected hard LOCKUP on cpu {cpu}",            "critical"),
    "SOFT_LOCKUP":          ("BUG: soft lockup - CPU#{cpu} stuck for 23s",            "warning"),
    "HUNG_TASK":            ("INFO: task kworker:{cpu} blocked for more than 120 seconds", "warning"),
    "GPU_BUS_DOWN":         ("NVRM: GPU at PCI:{bdf} has fallen off the bus",         "critical"),
    "EDAC_UE":              ("EDAC MC0: 1 UE memory read error on CPU_SrcID#0",       "critical"),
    "EDAC_CE":              ("EDAC MC0: 1 CE memory read error on CPU_SrcID#0",       "warning"),
    "MCE_HW_ERROR":         ("mce: [Hardware Error]: Machine check events logged",    "critical"),
    "PCIE_AER_FATAL":       ("pcieport {bdf}: PCIe Bus Error: severity=Uncorrectable (Fatal)", "critical"),
    "NVME_CONTROLLER_DOWN": ("nvme nvme0: controller is down; will reset",            "critical"),
    "FS_REMOUNT_RO":        ("EXT4-fs (sda1): Remounting filesystem read-only",       "critical"),
    "MLX5_FW_FATAL":        ("mlx5_core {bdf}: mlx5_health_report:115 firmware fatal error", "critical"),
    "NVIDIA_FABRIC_MANAGER_NOT_RUNNING": (
        "systemd: nvidia-fabricmanager.service: Unit not found.", "warning"
    ),
}

SXIDS = {
    20034: ("NVSWITCH_FATAL_LINK_ERROR", "critical"),
    20002: ("NVSWITCH_NON_FATAL",        "warning"),
}

SECRETS = [
    "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE",
    "password=hunter2",
    "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bdf(rng: random.Random) -> str:
    return f"0000:{rng.randint(0x10, 0xc1):02x}:00.0"


def ts(rng: random.Random, base: float = 1234500.0) -> float:
    return round(base + rng.uniform(0, 5000), 3)


@dataclass
class Block:
    sig_id: str
    raw_lines: list[str]
    expected: list[dict] = field(default_factory=list)
    note: str = ""


@dataclass
class Manifest:
    payload: dict
    note: str = ""


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

def s_known_xid(rng: random.Random, sig_id: str, code: int) -> Block:
    name, sev, action = XIDS[code]
    pci = bdf(rng)
    line = f"[{ts(rng)}] NVRM: Xid (PCI:{pci}): {code}, pid=1234, name=python3, Ch 00000010"
    return Block(
        sig_id,
        [line],
        expected=[{
            "family": "XID",
            "code": code,
            "name": name,
            "severity": sev,
            "action": action,
            "bdf": pci,
        }],
        note=f"known Xid {code} → {sev}",
    )


def s_unknown_xid(rng: random.Random, sig_id: str) -> Block:
    code = rng.choice([200, 201, 999])
    pci = bdf(rng)
    line = f"[{ts(rng)}] NVRM: Xid (PCI:{pci}): {code}, pid=4321"
    return Block(
        sig_id,
        [line],
        expected=[{
            "family": "UNKNOWN_XID",
            "code": code,
            "severity": "warning",
            "action": "escalate-for-review",
            "bdf": pci,
        }],
        note=f"unknown Xid {code} → must not invent severity",
    )


def s_log_family(rng: random.Random, sig_id: str, family: str) -> Block:
    tmpl, sev = LOG_FAMILIES[family]
    pci = bdf(rng)
    line = f"[{ts(rng)}] kernel: " + tmpl.format(bdf=pci, cpu=rng.randint(0, 95))
    exp: dict = {"family": family, "severity": sev}
    if "{bdf}" in tmpl:
        exp["bdf"] = pci
    return Block(sig_id, [line], expected=[exp], note=f"log → {family}")


def s_rma_pair(rng: random.Random, sig_a: str, sig_b: str) -> list[Block]:
    """Two independent critical signals on same BDF — should trigger RMA candidate."""
    pci = bdf(rng)
    a = Block(
        sig_a,
        [f"[{ts(rng)}] NVRM: Xid (PCI:{pci}): 48, pid=1234"],
        expected=[{
            "family": "XID", "code": 48, "name": "ECC_DBE",
            "severity": "critical", "action": "reset-gpu", "bdf": pci,
        }],
        note="RMA pair (1/2): Xid 48",
    )
    b = Block(
        sig_b,
        [f"[{ts(rng, base=1240000)}] NVRM: GPU at PCI:{pci} has fallen off the bus"],
        expected=[{
            "family": "GPU_BUS_DOWN", "severity": "critical", "bdf": pci,
            "rma_candidate": True,  # 2-signal rule satisfied within window
        }],
        note="RMA pair (2/2): bus-down on same BDF → rma_candidate=true",
    )
    return [a, b]


def s_vfio_suppress_fabric(rng: random.Random, sig_id: str) -> Block:
    """Under VFIO, FABRIC_MANAGER_NOT_RUNNING is expected — must be suppressed."""
    line = f"[{ts(rng)}] " + LOG_FAMILIES["NVIDIA_FABRIC_MANAGER_NOT_RUNNING"][0]
    return Block(
        sig_id,
        [line],
        expected=[],  # zero findings
        note="VFIO on → fabric-manager-not-running suppressed",
    )


def s_vfio_suppress_sxid(rng: random.Random, sig_id: str) -> Block:
    """SXid without paired Xid within 10s under VFIO → fabric isolation working."""
    line = f"[{ts(rng)}] NVRM: SXid (PCI:0000:8a:00.0): 20034, NVSWITCH_FATAL_LINK_ERROR"
    return Block(
        sig_id,
        [line],
        expected=[],
        note="VFIO on → solo SXid suppressed",
    )


def s_secret_scrub(rng: random.Random, sig_id: str) -> Block:
    """Critical line containing a secret — must be scrubbed in `verbatim`."""
    pci = bdf(rng)
    secret = rng.choice(SECRETS)
    line = (
        f"[{ts(rng)}] kernel: NVRM: Xid (PCI:{pci}): 46, pid=9 env={secret} app=trainer"
    )
    return Block(
        sig_id,
        [line],
        expected=[{
            "family": "XID", "code": 46, "name": "GPU_TIMEOUT",
            "severity": "critical", "action": "reset-gpu", "bdf": pci,
            "_verbatim_must_not_contain": secret,
        }],
        note="secret-bearing line → verbatim scrubbed",
    )


def s_burst_aggregate(rng: random.Random, sig_id: str, n: int = 60) -> Block:
    """Burst of N matching EDAC_CE lines on one BDF — must aggregate, cap at 50."""
    lines = []
    for i in range(n):
        lines.append(
            f"[{round(1234500 + i * 0.1, 3)}] EDAC MC0: 1 CE memory read error on CPU_SrcID#0 DIMM#{i % 4}"
        )
    return Block(
        sig_id,
        lines,
        expected=[{
            "family": "EDAC_CE",
            "severity": "warning",
            "count": n,
            "truncated": n > 50,
        }],
        note=f"burst of {n} EDAC_CE → aggregate, truncated if >50",
    )


# ---------------------------------------------------------------------------
# Scenario sets
# ---------------------------------------------------------------------------

def build_smoke(rng: random.Random) -> list[Block | Manifest]:
    out: list[Block | Manifest] = [
        Manifest({"node": "h100-04", "vfio_passthrough": False, "gpu_count": 8}),
        s_known_xid(rng, "s-001", 48),
        s_known_xid(rng, "s-002", 79),
        s_known_xid(rng, "s-003", 92),
        s_log_family(rng, "s-004", "HARD_LOCKUP"),
        s_log_family(rng, "s-005", "MLX5_FW_FATAL"),
    ]
    return out


def build_rma(rng: random.Random) -> list[Block | Manifest]:
    pair = s_rma_pair(rng, "r-001", "r-002")
    return [
        Manifest({"node": "h100-12", "vfio_passthrough": False, "gpu_count": 8}),
        pair[0],
        s_log_family(rng, "r-pad", "SOFT_LOCKUP"),  # unrelated noise
        pair[1],
    ]


def build_vfio(rng: random.Random) -> list[Block | Manifest]:
    return [
        Manifest({"node": "h100-vfio-01", "vfio_passthrough": True, "gpu_count": 8}),
        s_vfio_suppress_fabric(rng, "v-001"),
        s_vfio_suppress_sxid(rng, "v-002"),
        s_known_xid(rng, "v-003", 46),  # real Xid → still emits
        Manifest({"node": "h100-vfio-01", "vfio_passthrough": False, "gpu_count": 8}),
        s_log_family(rng, "v-004", "NVIDIA_FABRIC_MANAGER_NOT_RUNNING"),  # now NOT suppressed
    ]


def build_unknown(rng: random.Random) -> list[Block | Manifest]:
    return [
        Manifest({"node": "h100-77", "vfio_passthrough": False, "gpu_count": 8}),
        s_unknown_xid(rng, "u-001"),
        s_unknown_xid(rng, "u-002"),
        s_secret_scrub(rng, "u-003"),
        s_burst_aggregate(rng, "u-004", n=60),
    ]


def build_all(rng: random.Random) -> list[Block | Manifest]:  # noqa: ARG001
    return [
        *build_smoke(random.Random(1)),
        *build_rma(random.Random(2)),
        *build_vfio(random.Random(3)),
        *build_unknown(random.Random(4)),
    ]


SCENARIOS = {
    "smoke":   build_smoke,
    "rma":     build_rma,
    "vfio":    build_vfio,
    "unknown": build_unknown,
    "all":     build_all,
}


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------

def write_feed(items: list[Block | Manifest], path: Path) -> None:
    with path.open("w") as f:
        for it in items:
            if isinstance(it, Manifest):
                f.write(f"MANIFEST {json.dumps(it.payload)}\n")
            else:
                f.write(f"SIGNAL {it.sig_id}\n")
                for line in it.raw_lines:
                    f.write(line + "\n")
                f.write("END\n")
        f.write("SHUTDOWN\n")


def write_golden(items: list[Block | Manifest], path: Path) -> None:
    with path.open("w") as f:
        for it in items:
            if isinstance(it, Manifest):
                continue
            record = {
                "signal_id": it.sig_id,
                "note": it.note,
                "expected_findings": it.expected,
            }
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scenarios", default="all", choices=list(SCENARIOS))
    ap.add_argument("--out-feed", default="feed.synthetic.txt")
    ap.add_argument("--out-golden", default="expected.synthetic.jsonl")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    items = SCENARIOS[args.scenarios](rng)

    feed_path = OUT_DIR / args.out_feed
    golden_path = OUT_DIR / args.out_golden
    write_feed(items, feed_path)
    write_golden(items, golden_path)

    n_signals = sum(1 for it in items if isinstance(it, Block))
    n_manifest = sum(1 for it in items if isinstance(it, Manifest))
    n_expected = sum(len(it.expected) for it in items if isinstance(it, Block))
    print(f"wrote {feed_path}")
    print(f"  signals:           {n_signals}")
    print(f"  manifests:         {n_manifest}")
    print(f"  expected findings: {n_expected}")
    print(f"wrote {golden_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
