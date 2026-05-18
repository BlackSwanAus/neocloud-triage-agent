"""
Performance baseline — measure wall time, turns, and tokens per signal.

This is NOT a pass/fail test — it's an instrumentation harness.
Run with --capture=no to see numbers; the recorded baselines feed the
optimization decisions in BENCHMARK.md.

Skipped unless RUN_LIVE_AGENT_TESTS=1 (each run costs ~$0.08).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

AGENT_DIR = Path(__file__).resolve().parent.parent
AGENT_MD = AGENT_DIR / "AGENT.md"
BENCH_LOG = AGENT_DIR / "tests" / "bench_log.jsonl"

pytestmark = pytest.mark.asyncio


# Signals we want baselines for. Cover the easy/hard spectrum.
SIGNALS = {
    "hot_xid_48": (  # known hot Xid → ideally answerable from hot table alone
        "[1234567.890] NVRM: Xid (PCI:0000:18:00.0): 48, pid=12345, name=python3"
    ),
    "cold_xid_119": (  # less common, may need full catalog read
        "[1234567.890] NVRM: Xid (PCI:0000:18:00.0): 119, pid=12345, name=python3"
    ),
    "log_pattern_gpu_bus": (  # log family path, not Xid path
        "[1234600.123] kernel: NVRM: GPU at PCI:0000:1a:00 has fallen off the bus"
    ),
}


async def _run_one(signal_id: str, raw: str, model: str) -> dict:
    """Run one signal end-to-end; return wall-time + token + turn metrics."""
    options = ClaudeAgentOptions(
        system_prompt=AGENT_MD.read_text(),
        cwd=str(AGENT_DIR),
        permission_mode="bypassPermissions",
        allowed_tools=["Read", "Glob", "Grep"],
        model=model,
        max_turns=12,
    )
    t0 = time.monotonic()
    final: ResultMessage | None = None
    chunks: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(f"SIGNAL {signal_id}\n{raw}\nEND")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        chunks.append(b.text)
            elif isinstance(msg, ResultMessage):
                final = msg
    elapsed = time.monotonic() - t0
    assert final is not None

    usage = final.usage or {}
    return {
        "signal_id": signal_id,
        "model": model,
        "wall_seconds": round(elapsed, 2),
        "num_turns": final.num_turns,
        "is_error": final.is_error,
        "errors": getattr(final, "errors", None),
        "duration_api_ms": final.duration_api_ms,
        "cost_usd": final.total_cost_usd,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "output_chars": sum(len(c) for c in chunks),
    }


def _append_bench(record: dict, tag: str) -> None:
    record["tag"] = tag
    record["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    BENCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with BENCH_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AGENT_TESTS") != "1",
    reason="set RUN_LIVE_AGENT_TESTS=1 to hit the real model",
)
@pytest.mark.parametrize("signal_id,raw", list(SIGNALS.items()))
async def test_baseline_per_signal(signal_id: str, raw: str):
    tag = os.environ.get("BENCH_TAG", "baseline")
    model = os.environ.get("TRIAGE_TEST_MODEL", "claude-haiku-4-5-20251001")
    record = await _run_one(signal_id, raw, model)
    _append_bench(record, tag)
    print(f"\n[bench:{tag}] {signal_id}: {record}")
    # Soft assertions — don't fail the suite, just surface regressions.
    assert not record["is_error"], f"agent errored: {record['errors']}"
