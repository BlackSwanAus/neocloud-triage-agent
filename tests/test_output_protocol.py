"""
Output protocol test — RED.

Verifies that the real model, given AGENT.md as its system prompt, emits
output our validator can parse for a single SIGNAL block.

Expected (likely-failing) shape per AGENT.md contract:

    FINDING <signal-id>
    {"family": "XID", "code": 48, ...}
    END
    READY

Common ways this will fail without further prompt engineering:
  - Model wraps JSON in ```json fences
  - Model adds prose preamble ("I'll analyze this...")
  - Model uses different ID than the SIGNAL header
  - Model omits READY or END
  - Model uses a different shape (markdown table, multi-line JSON)

This test pins the contract before we iterate AGENT.md.
"""
from __future__ import annotations

import os
import re
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

pytestmark = pytest.mark.asyncio


FINDING_HEADER = re.compile(r"^FINDING\s+(\S+)\s*$", re.MULTILINE)


async def _run_one_signal(signal_id: str, raw_line: str, model: str) -> str:
    """Send one SIGNAL block, return concatenated text from the assistant."""
    options = ClaudeAgentOptions(
        system_prompt=AGENT_MD.read_text(),
        cwd=str(AGENT_DIR),
        permission_mode="bypassPermissions",
        allowed_tools=["Read", "Glob", "Grep"],
        model=model,
        max_turns=12,  # skill lookup + tool reads can take several turns
    )
    messages: list[str] = []
    result: ResultMessage | None = None
    async with ClaudeSDKClient(options=options) as client:
        await client.query(f"SIGNAL {signal_id}\n{raw_line}\nEND")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                # Join text blocks within one message directly; separate messages
                # with newlines so structured output isn't run-together with prose.
                text = "".join(b.text for b in msg.content if isinstance(b, TextBlock))
                if text:
                    messages.append(text)
            elif isinstance(msg, ResultMessage):
                result = msg
    assert result is not None, "no ResultMessage"
    assert not result.is_error, f"agent error: {getattr(result, 'errors', None)}"
    return "\n".join(messages)


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AGENT_TESTS") != "1",
    reason="set RUN_LIVE_AGENT_TESTS=1 to hit the real model",
)
async def test_xid_48_produces_parseable_finding_block():
    out = await _run_one_signal(
        signal_id="t-001",
        raw_line=(
            "[1234567.890] NVRM: Xid (PCI:0000:18:00.0): 48, pid=12345, "
            "name=python3, Ch 00000010"
        ),
        model=os.environ.get("TRIAGE_TEST_MODEL", "claude-haiku-4-5-20251001"),
    )

    # Dump on failure so we can iterate the prompt.
    print("\n=== RAW AGENT OUTPUT ===\n" + out + "\n=== END ===")

    # 1. FINDING header with matching signal id
    m = FINDING_HEADER.search(out)
    assert m, "no FINDING header in output"
    assert m.group(1) == "t-001", f"signal id mismatch: {m.group(1)}"

    # 2. There must be an END after the FINDING header
    after_header = out[m.end():]
    assert "\nEND" in after_header, "no END terminator after FINDING block"
    body = after_header.split("\nEND", 1)[0]

    # 3. Body must contain at least one parseable JSON object
    import json
    json_lines = [
        ln for ln in body.splitlines()
        if ln.strip().startswith("{") and ln.strip().endswith("}")
    ]
    assert json_lines, f"no JSON-object lines in body: {body!r}"
    obj = json.loads(json_lines[0])

    # 4. Required fields per AGENT.md contract
    assert obj.get("family") == "XID", f"family != XID: {obj}"
    assert obj.get("code") == 48, f"code != 48: {obj}"
    assert obj.get("severity") == "critical", f"severity != critical: {obj}"
    assert obj.get("bdf") == "0000:18:00.0", f"bdf mismatch: {obj}"

    # 5. READY sentinel (loop contract)
    assert "READY" in out, "no READY sentinel — agent did not signal turn complete"
