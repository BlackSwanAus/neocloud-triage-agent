#!/usr/bin/env python3
"""
Synthetic DCGM-exporter fixture generator.

Edge detection needs consecutive scrapes (a "before" and "after"), so scenarios
are ordered lists of snapshots. This script:

  1. Renders each snapshot as a Prometheus-exposition `.prom` file (inspectable
     fixture of exactly what dcgm-exporter would expose).
  2. Runs the *real* dcgm_poller edge engine over the snapshot sequence with a
     single fresh state — producing the deterministic SIGNAL feed the agent sees.
  3. Writes the agent-input feed (`feed.dcgm.txt`) and the golden
     (`expected.dcgm.jsonl`) pairing each emitted SIGNAL id to its expected
     finding.

Because the poller is deterministic, SIGNAL ids are stable (dcgm-00001, …).

Usage:
  python gen_dcgm_synthetic.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
REPO = OUT_DIR.parent.parent
sys.path.insert(0, str(REPO))

import dcgm_poller as dp  # noqa: E402

MODEL = "NVIDIA H100 80GB HBM3"


def render_snapshot(gpu: str, bdf: str, metrics: dict[str, float]) -> str:
    """Render one GPU's metrics as dcgm-exporter exposition text."""
    lines = []
    for metric, value in metrics.items():
        labels = f'gpu="{gpu}",UUID="GPU-{gpu}",pci_bus_id="{bdf}",device="nvidia{gpu}",modelName="{MODEL}"'
        # dcgm-exporter prints integers without a decimal point
        v = int(value) if float(value).is_integer() else value
        lines.append(f"{metric}{{{labels}}} {v}")
    return "\n".join(lines) + "\n"


# A scenario = (name, gpu, bdf, [(metrics_snapshot, [expected_findings_for_emissions]), ...])
# Each snapshot's expected list pairs (in order) with the emissions the poller
# produces for that snapshot. An empty list means "this snapshot emits nothing".
SCENARIOS = [
    (
        "dbe", "0", "00000000:18:00.0",
        [
            ({"DCGM_FI_DEV_GPU_TEMP": 65, "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL": 0,
              "DCGM_FI_DEV_XID_ERRORS": 0}, []),
            # DBE 0->1 and a new XID code 48 on the same GPU, same scrape.
            ({"DCGM_FI_DEV_GPU_TEMP": 65, "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL": 1,
              "DCGM_FI_DEV_XID_ERRORS": 48},
             [
                 {"family": "DCGM_ECC_DBE", "severity": "critical",
                  "action": "reset-gpu", "bdf": "0000:18:00.0"},
                 {"family": "XID", "code": 48, "severity": "critical",
                  "action": "reset-gpu", "bdf": "0000:18:00.0"},
             ]),
        ],
    ),
    (
        "overtemp", "2", "00000000:65:00.0",
        [
            ({"DCGM_FI_DEV_GPU_TEMP": 87}, []),
            ({"DCGM_FI_DEV_GPU_TEMP": 93},
             [{"family": "DCGM_GPU_OVERTEMP", "severity": "critical",
               "action": "reset-gpu", "bdf": "0000:65:00.0"}]),
            # still warm (88) — must NOT re-fire
            ({"DCGM_FI_DEV_GPU_TEMP": 88}, []),
        ],
    ),
    (
        "throttle", "4", "00000000:9e:00.0",
        [
            ({"DCGM_FI_DEV_CLOCK_THROTTLE_REASONS": dp.HW_FAULT_MASK}, []),
            ({"DCGM_FI_DEV_CLOCK_THROTTLE_REASONS": dp.HW_FAULT_MASK}, []),
            # third consecutive bad poll — fires once
            ({"DCGM_FI_DEV_CLOCK_THROTTLE_REASONS": dp.HW_FAULT_MASK},
             [{"family": "DCGM_PERSISTENT_THROTTLE", "severity": "warning",
               "action": "monitor", "bdf": "0000:9e:00.0"}]),
        ],
    ),
    (
        "quiet", "6", "00000000:c1:00.0",
        [
            ({"DCGM_FI_DEV_GPU_TEMP": 62, "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL": 0,
              "DCGM_FI_DEV_ECC_SBE_VOL_TOTAL": 0, "DCGM_FI_DEV_XID_ERRORS": 0,
              "DCGM_FI_DEV_PCIE_REPLAY_COUNTER": 0,
              "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS": 0}, []),
        ],
    ),
]


def main() -> int:
    state = dp.new_state()
    feed_parts: list[str] = []
    golden: list[dict] = []
    snap_dir = OUT_DIR / "snapshots"
    snap_dir.mkdir(exist_ok=True)

    for name, gpu, bdf, snaps in SCENARIOS:
        for i, (metrics, expected) in enumerate(snaps):
            text = render_snapshot(gpu, bdf, metrics)
            (snap_dir / f"{name}-{i}.prom").write_text(text)

            blocks = dp.run_once(text, state)
            if len(blocks) != len(expected):
                sys.stderr.write(
                    f"[gen] scenario {name} snap {i}: poller emitted {len(blocks)} "
                    f"signal(s) but {len(expected)} expected — fix the scenario.\n"
                )
                return 1
            for block, exp in zip(blocks, expected):
                feed_parts.append(block)
                sig_id = block.splitlines()[0].split()[1]
                golden.append({
                    "signal_id": sig_id,
                    "note": f"{name} → {exp['family']}",
                    "expected_findings": [exp],
                })

    feed_parts.append("SHUTDOWN\n")
    (OUT_DIR / "feed.dcgm.txt").write_text("".join(feed_parts))
    with (OUT_DIR / "expected.dcgm.jsonl").open("w") as f:
        for record in golden:
            f.write(json.dumps(record) + "\n")

    print(f"wrote {OUT_DIR / 'feed.dcgm.txt'}")
    print(f"  scenarios:  {len(SCENARIOS)}")
    print(f"  signals:    {len(golden)}")
    print(f"  snapshots:  {sum(len(s[3]) for s in SCENARIOS)} (under snapshots/)")
    print(f"wrote {OUT_DIR / 'expected.dcgm.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
