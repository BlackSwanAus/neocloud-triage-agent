"""
Unit tests for dcgm_poller.py — pure, no model calls, no network.

Covers the logic that turns continuous DCGM-exporter telemetry into *valid*
(deduplicated, restart-safe, non-flapping, noise-gated) SIGNAL blocks:
  - Prometheus exposition parsing
  - pci_bus_id -> canonical BDF normalization
  - counter edge detection (emit on increase, once)
  - counter-reset robustness (no spurious negative delta)
  - gauge threshold crossing with hysteresis re-arm
  - XID_ERRORS code-transition handling (value is a code, not a count)
  - persistent-throttle gate (fire only after N consecutive bad polls)
  - state file round-trip + cross-restart suppression
  - quiet scrape -> zero signals
  - emitted SIGNAL is consumable by runner.read_block
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

import dcgm_poller as dp  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _line(metric: str, value, bdf="00000000:18:00.0", gpu="0", extra="") -> str:
    labels = f'gpu="{gpu}",pci_bus_id="{bdf}",modelName="NVIDIA H100 80GB HBM3"'
    if extra:
        labels += "," + extra
    return f"{metric}{{{labels}}} {value}"


def _emit(text: str, state: dict) -> list[dp.Emission]:
    """Parse one scrape's text and run edge detection against state (mutates state)."""
    return dp.detect_edges(dp.parse_metrics(text), state)


# ---------------------------------------------------------------------------
# parsing + normalization
# ---------------------------------------------------------------------------

def test_parse_metrics_line():
    text = (
        "# HELP DCGM_FI_DEV_GPU_TEMP GPU temperature (in C).\n"
        "# TYPE DCGM_FI_DEV_GPU_TEMP gauge\n"
        + _line("DCGM_FI_DEV_GPU_TEMP", 71)
        + "\n"
    )
    samples = dp.parse_metrics(text)
    assert len(samples) == 1
    s = samples[0]
    assert s.metric == "DCGM_FI_DEV_GPU_TEMP"
    assert s.value == 71.0
    assert s.labels["gpu"] == "0"
    assert s.labels["pci_bus_id"] == "00000000:18:00.0"
    assert s.raw == _line("DCGM_FI_DEV_GPU_TEMP", 71)


def test_parse_skips_comments_and_blanks():
    text = "# comment\n\n# TYPE x gauge\n" + _line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 0) + "\n"
    samples = dp.parse_metrics(text)
    assert len(samples) == 1


def test_bdf_normalization():
    assert dp.normalize_bdf("00000000:3B:00.0") == "0000:3b:00.0"
    assert dp.normalize_bdf("00000000:18:00.0") == "0000:18:00.0"
    # already-canonical input is left well-formed
    assert dp.normalize_bdf("0000:c1:00.0") == "0000:c1:00.0"


# ---------------------------------------------------------------------------
# counter edges
# ---------------------------------------------------------------------------

def test_counter_edge_emits_once():
    state = dp.new_state()
    m = "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL"

    # baseline 0 -> no emit
    assert _emit(_line(m, 0), state) == []
    # 0 -> 1 -> one emission carrying the delta
    ems = _emit(_line(m, 1), state)
    assert len(ems) == 1
    assert "delta 1" in ems[0].comment
    # flat re-scrape at 1 -> silent
    assert _emit(_line(m, 1), state) == []


def test_counter_first_sight_nonzero_emits():
    state = dp.new_state()
    ems = _emit(_line("DCGM_FI_DEV_PCIE_REPLAY_COUNTER", 7), state)
    assert len(ems) == 1  # a fault already present at startup must surface


def test_counter_reset_handling():
    state = dp.new_state()
    m = "DCGM_FI_DEV_ECC_SBE_VOL_TOTAL"

    assert len(_emit(_line(m, 5), state)) == 1          # first sight 5 -> emit delta 5
    # exporter/driver restart drops counter to 0 -> no emit, no negative delta
    assert _emit(_line(m, 0), state) == []
    # climbs again to 2 -> emit delta 2 (from the new 0 baseline, not -3)
    ems = _emit(_line(m, 2), state)
    assert len(ems) == 1
    assert "delta 2" in ems[0].comment


# ---------------------------------------------------------------------------
# gauge thresholds
# ---------------------------------------------------------------------------

def test_gauge_threshold_crossing_and_rearm():
    state = dp.new_state()
    m = "DCGM_FI_DEV_GPU_TEMP"  # threshold 90, hysteresis 2

    assert _emit(_line(m, 87), state) == []     # below
    assert len(_emit(_line(m, 93), state)) == 1 # cross 90 -> fire
    assert _emit(_line(m, 92), state) == []     # still high -> silent (no flap)
    assert _emit(_line(m, 88), state) == []     # drop below 90-2=88? 88 is not < 88 -> still armed-fired
    assert _emit(_line(m, 87), state) == []     # < 88 -> re-arm, no emit
    assert len(_emit(_line(m, 93), state)) == 1 # cross again -> fire again


# ---------------------------------------------------------------------------
# XID code-valued field
# ---------------------------------------------------------------------------

def test_xid_code_transition():
    state = dp.new_state()
    m = "DCGM_FI_DEV_XID_ERRORS"

    assert _emit(_line(m, 0), state) == []          # no error
    ems = _emit(_line(m, 48), state)                # new non-zero code -> emit
    assert len(ems) == 1
    assert "48" in ems[0].comment
    assert _emit(_line(m, 48), state) == []         # same code again -> silent
    assert _emit(_line(m, 0), state) == []          # cleared -> silent
    assert len(_emit(_line(m, 79), state)) == 1     # different code -> emit


# ---------------------------------------------------------------------------
# persistent throttle gate
# ---------------------------------------------------------------------------

def test_throttle_persistence_gate():
    state = dp.new_state()
    m = "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS"
    hw = dp.HW_FAULT_MASK  # a HW-fault throttle bitmask value

    assert _emit(_line(m, hw), state) == []         # poll 1 -> arming
    assert _emit(_line(m, hw), state) == []         # poll 2 -> arming
    assert len(_emit(_line(m, hw), state)) == 1     # poll 3 -> fire once
    assert _emit(_line(m, hw), state) == []         # poll 4 -> already fired, silent


def test_throttle_benign_bits_never_fire():
    state = dp.new_state()
    m = "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS"
    benign = 0x1 | 0x2 | 0x4  # idle / app-clocks / sw-power-cap: not HW faults
    for _ in range(5):
        assert _emit(_line(m, benign), state) == []


# ---------------------------------------------------------------------------
# state persistence / restart safety
# ---------------------------------------------------------------------------

def test_state_roundtrip(tmp_path):
    state = dp.new_state()
    _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 1), state)
    p = tmp_path / "dcgm.state"
    dp.save_state(p, state)
    loaded = dp.load_state(p)
    assert loaded == state


def test_reported_fault_suppressed_across_restart(tmp_path):
    m = "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL"
    p = tmp_path / "dcgm.state"

    state = dp.load_state(p)                 # missing file -> fresh state
    assert len(_emit(_line(m, 1), state)) == 1
    dp.save_state(p, state)

    # "restart": reload state, same value still present -> must NOT re-fire
    state2 = dp.load_state(p)
    assert _emit(_line(m, 1), state2) == []


def test_load_missing_state_returns_fresh(tmp_path):
    state = dp.load_state(tmp_path / "nope.state")
    assert state == dp.new_state()


# ---------------------------------------------------------------------------
# quiet scrape
# ---------------------------------------------------------------------------

def test_quiet_scrape_zero_signals():
    state = dp.new_state()
    text = "\n".join([
        _line("DCGM_FI_DEV_GPU_TEMP", 64),
        _line("DCGM_FI_DEV_MEMORY_TEMP", 70),
        _line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 0),
        _line("DCGM_FI_DEV_ECC_SBE_VOL_TOTAL", 0),
        _line("DCGM_FI_DEV_XID_ERRORS", 0),
        _line("DCGM_FI_DEV_PCIE_REPLAY_COUNTER", 0),
        _line("DCGM_FI_DEV_CLOCK_THROTTLE_REASONS", 0),
    ])
    assert _emit(text, state) == []


def test_unknown_metric_ignored():
    state = dp.new_state()
    # a metric with no rule (e.g. utilization) must never produce a signal
    assert _emit(_line("DCGM_FI_DEV_GPU_UTIL", 100), state) == []


# ---------------------------------------------------------------------------
# emission rendering + feed-contract glue
# ---------------------------------------------------------------------------

def test_render_signal_shape():
    state = dp.new_state()
    _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 0), state)
    ems = _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 1), state)
    block = dp.render_signal(ems[0])
    lines = block.splitlines()
    assert lines[0].startswith("SIGNAL dcgm-")
    assert lines[-1] == "END"
    assert any("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL" in ln for ln in lines)


def test_signal_ids_are_monotonic():
    state = dp.new_state()
    _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 0), state)
    a = _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 1), state)[0]
    b = _emit(_line("DCGM_FI_DEV_PCIE_REPLAY_COUNTER", 1), state)[0]
    assert a.sig_id != b.sig_id
    assert a.sig_id < b.sig_id  # zero-padded monotonic


def test_emitted_signal_parses_as_feed_block():
    """The poller's output must be a valid feed block runner.read_block accepts."""
    import runner  # imports claude_agent_sdk; installed in dev venv

    state = dp.new_state()
    _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 0), state)
    em = _emit(_line("DCGM_FI_DEV_ECC_DBE_VOL_TOTAL", 1), state)[0]
    block = dp.render_signal(em)

    async def _read():
        reader = asyncio.StreamReader()
        reader.feed_data(block.encode())
        reader.feed_eof()
        return await runner.read_block(reader)

    kind, payload = asyncio.run(_read())
    assert kind == f"signal:{em.sig_id}"
    assert "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL" in payload
