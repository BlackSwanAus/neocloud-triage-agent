#!/usr/bin/env python3
"""
DCGM-exporter telemetry poller for the Neocloud Triage Agent.

Scrapes an NVIDIA dcgm-exporter `/metrics` endpoint (or a fixture file), applies
edge detection so continuous telemetry becomes *valid* (deduplicated,
restart-safe, non-flapping, noise-gated) discrete events, and writes SIGNAL
blocks the agent's runner.py consumes unchanged.

The poller does NO classification — it only decides *when* a reading is a new
event worth a signal and emits the raw DCGM sample line. The agent classifies it
against the DCGM hot table in AGENT.md (family / severity / action).

Edge rules (keyed by metric name + canonical BDF):
  - counter   : emit when the value increases (carry delta); reset-safe.
  - gauge     : emit on below->above threshold crossing; re-arm on drop past hysteresis.
  - xid       : DCGM_FI_DEV_XID_ERRORS value is the *last Xid code*, not a count —
                emit on transition to a new non-zero code.
  - throttle  : DCGM_FI_DEV_CLOCK_THROTTLE_REASONS bitmask — emit only after the
                HW-fault bits stay set for N consecutive polls (noise gate).

Usage:
  python dcgm_poller.py --fixture examples/dcgm/h100-dbe.after.prom --state /tmp/dcgm.state --once
  python dcgm_poller.py --endpoint http://localhost:9400/metrics --state ~/.dcgm.state --interval 15 --out /var/run/triage.fifo
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# DCGM/NVML clock-throttle reason bits we treat as hardware faults. Benign bits
# (GPU idle 0x1, app-clocks 0x2, sw-power-cap 0x4, sync-boost 0x10, display 0x100)
# are excluded so routine clock management never becomes a finding.
_HW_SLOWDOWN = 0x8
_SW_THERMAL = 0x20
_HW_THERMAL = 0x40
_HW_POWER_BRAKE = 0x80
HW_FAULT_MASK = _HW_SLOWDOWN | _SW_THERMAL | _HW_THERMAL | _HW_POWER_BRAKE  # 0xE8


@dataclass(frozen=True)
class Rule:
    kind: str  # "counter" | "gauge" | "xid" | "throttle"
    threshold: float = 0.0
    hysteresis: float = 2.0
    min_consecutive: int = 3


# Threshold values are the canonical source of truth; the dcgm-telemetry skill
# documents the same numbers and their rationale. Severities/actions live in
# AGENT.md (the agent classifies; the poller only gates emission).
RULES: dict[str, Rule] = {
    "DCGM_FI_DEV_XID_ERRORS":                    Rule("xid"),
    "DCGM_FI_DEV_ECC_DBE_VOL_TOTAL":             Rule("counter"),
    "DCGM_FI_DEV_ECC_SBE_VOL_TOTAL":             Rule("counter"),
    "DCGM_FI_DEV_RETIRED_DBE":                   Rule("counter"),
    "DCGM_FI_DEV_ROW_REMAP_FAILURE":             Rule("counter"),
    "DCGM_FI_DEV_PCIE_REPLAY_COUNTER":           Rule("counter"),
    "DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL": Rule("counter"),
    "DCGM_FI_DEV_THERMAL_VIOLATION":             Rule("counter"),
    "DCGM_FI_DEV_POWER_VIOLATION":               Rule("counter"),
    "DCGM_FI_DEV_GPU_TEMP":                      Rule("gauge", threshold=90.0, hysteresis=2.0),
    "DCGM_FI_DEV_MEMORY_TEMP":                   Rule("gauge", threshold=95.0, hysteresis=2.0),
    "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS":        Rule("throttle", min_consecutive=3),
}


@dataclass
class Sample:
    metric: str
    labels: dict[str, str]
    value: float
    raw: str


@dataclass
class Emission:
    sig_id: str
    comment: str
    raw: str


# ---------------------------------------------------------------------------
# parsing + normalization
# ---------------------------------------------------------------------------

_LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def parse_metrics(text: str) -> list[Sample]:
    """Parse Prometheus exposition text into Samples. Skips comments/blanks."""
    samples: list[Sample] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            name = line[: line.index("{")]
            labels_blob = line[line.index("{") + 1 : line.rindex("}")]
            rest = line[line.rindex("}") + 1 :].strip()
        else:
            name, _, rest = line.partition(" ")
            labels_blob = ""
        rest = rest.strip()
        if not rest:
            continue
        try:
            value = float(rest.split()[0])
        except ValueError:
            continue
        if value != value:  # NaN
            continue
        labels = dict(_LABEL_RE.findall(labels_blob))
        samples.append(Sample(metric=name, labels=labels, value=value, raw=line))
    return samples


def normalize_bdf(pci_bus_id: str) -> str:
    """DCGM `00000000:3B:00.0` -> canonical Linux `0000:3b:00.0`."""
    s = pci_bus_id.strip().lower()
    parts = s.split(":")
    if len(parts) != 3:
        return s
    domain, bus, devfunc = parts
    domain = domain[-4:].rjust(4, "0")
    return f"{domain}:{bus}:{devfunc}"


def _bdf_of(sample: Sample) -> str:
    pci = sample.labels.get("pci_bus_id")
    if pci:
        return normalize_bdf(pci)
    return "gpu:" + sample.labels.get("gpu", "?")


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def new_state() -> dict:
    return {"version": 1, "seq": 0, "counters": {}, "xid": {}, "gauges": {}, "throttle": {}}


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return new_state()
    state = json.loads(p.read_text())
    base = new_state()
    base.update(state)
    return base


def save_state(path: str | Path, state: dict) -> None:
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, p)  # atomic


# ---------------------------------------------------------------------------
# edge detection
# ---------------------------------------------------------------------------

def detect_edges(samples: list[Sample], state: dict) -> list[Emission]:
    """Apply per-metric edge rules. Mutates `state`; returns emissions in order."""
    out: list[Emission] = []
    for s in samples:
        rule = RULES.get(s.metric)
        if rule is None:
            continue
        key = f"{s.metric}|{_bdf_of(s)}"
        if rule.kind == "counter":
            _counter(s, key, state, out)
        elif rule.kind == "gauge":
            _gauge(s, key, rule, state, out)
        elif rule.kind == "xid":
            _xid(s, key, state, out)
        elif rule.kind == "throttle":
            _throttle(s, key, rule, state, out)
    return out


def _emit(state: dict, comment: str, raw: str, out: list[Emission]) -> None:
    state["seq"] += 1
    out.append(Emission(f"dcgm-{state['seq']:05d}", comment, raw))


def _counter(s: Sample, key: str, state: dict, out: list[Emission]) -> None:
    last = state["counters"].get(key, 0.0)
    value = s.value
    if value > last:
        delta = value - last
        _emit(state, f"counter {s.metric} increased {last:g} -> {value:g} (delta {delta:g})", s.raw, out)
    elif value < last and value > 0:
        # counter reset (exporter/driver restart) then re-accumulated within one gap
        _emit(state, f"counter {s.metric} reset, now {value:g} (delta {value:g})", s.raw, out)
    state["counters"][key] = value


def _gauge(s: Sample, key: str, rule: Rule, state: dict, out: list[Emission]) -> None:
    g = state["gauges"].get(key, {"fired": False})
    value = s.value
    if value >= rule.threshold and not g["fired"]:
        _emit(state, f"gauge {s.metric} {value:g} >= threshold {rule.threshold:g}", s.raw, out)
        g["fired"] = True
    elif value < rule.threshold - rule.hysteresis and g["fired"]:
        g["fired"] = False  # re-arm, no emit
    state["gauges"][key] = g


def _xid(s: Sample, key: str, state: dict, out: list[Emission]) -> None:
    code = int(s.value)
    prev = state["xid"].get(key, 0)
    if code != 0 and code != prev:
        _emit(state, f"xid code {code} observed via DCGM_FI_DEV_XID_ERRORS", s.raw, out)
    state["xid"][key] = code


def _throttle(s: Sample, key: str, rule: Rule, state: dict, out: list[Emission]) -> None:
    t = state["throttle"].get(key, {"consecutive": 0})
    bad = int(s.value) & HW_FAULT_MASK
    t["consecutive"] = t["consecutive"] + 1 if bad else 0
    if t["consecutive"] == rule.min_consecutive:
        _emit(state, f"persistent HW throttle (reasons=0x{bad:x}) for {rule.min_consecutive} polls", s.raw, out)
    state["throttle"][key] = t


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_signal(em: Emission) -> str:
    """Render one Emission as a feed SIGNAL block (consumed by runner.read_block)."""
    return f"SIGNAL {em.sig_id}\n# dcgm-exporter edge: {em.comment}\n{em.raw}\nEND\n"


# ---------------------------------------------------------------------------
# scrape + run
# ---------------------------------------------------------------------------

def scrape(endpoint: str | None, fixture: str | None, timeout: float = 10.0) -> str:
    """Fetch metrics text from an HTTP endpoint or a fixture file."""
    if fixture:
        return Path(fixture).read_text()
    if endpoint:
        with urllib.request.urlopen(endpoint, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", "replace")
    raise ValueError("scrape requires --endpoint or --fixture")


def run_once(text: str, state: dict) -> list[str]:
    """Parse one scrape, detect edges, return rendered SIGNAL blocks."""
    return [render_signal(em) for em in detect_edges(parse_metrics(text), state)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="DCGM-exporter telemetry poller")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--endpoint", help="dcgm-exporter /metrics URL")
    src.add_argument("--fixture", help="Prometheus-text fixture file")
    ap.add_argument("--state", default="dcgm.state", help="poller state file (JSON)")
    ap.add_argument("--out", default="-", help="output feed path or '-' for stdout")
    ap.add_argument("--interval", type=float, default=15.0, help="seconds between scrapes")
    ap.add_argument("--once", action="store_true", help="scrape once and exit")
    return ap.parse_args(argv)


def _write(blocks: list[str], out_path: str) -> None:
    if not blocks:
        return
    payload = "".join(blocks)
    if out_path == "-":
        sys.stdout.write(payload)
        sys.stdout.flush()
    else:
        with open(out_path, "a") as f:
            f.write(payload)
            f.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state = load_state(args.state)
    while True:
        text = scrape(args.endpoint, args.fixture)
        blocks = run_once(text, state)
        _write(blocks, args.out)
        save_state(args.state, state)
        sys.stderr.write(f"[dcgm_poller] scrape -> {len(blocks)} signal(s)\n")
        if args.once or args.fixture:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
