"""
SDK smoke test — RED before runner.py is rewritten.

Verifies, against the *real* claude-agent-sdk + real Max-credential auth:
  1. ClaudeSDKClient can be opened as `async with`.
  2. A one-shot query returns at least one AssistantMessage with a TextBlock.
  3. The assistant follows a trivial instruction ("reply with only OK").
  4. ResultMessage signals is_error=False.

Conditions:
  - claude-agent-sdk installed (we verified 0.2.82).
  - `claude` CLI installed and logged in (verified 2.1.143).
  - ANTHROPIC_API_KEY MUST be unset for the Max-auth path to be exercised
    (the CLI prefers env key over stored OAuth — see README caveat).

Run:
  ANTHROPIC_API_KEY= python -m pytest tests/test_sdk_smoke.py -s
"""
from __future__ import annotations

import os
import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)


pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AGENT_TESTS") != "1",
    reason="set RUN_LIVE_AGENT_TESTS=1 to hit the real model",
)
async def test_one_shot_query_returns_ok():
    """Open client, ask for OK, assert OK comes back."""
    options = ClaudeAgentOptions(
        system_prompt=(
            "You are a test harness. Respond with the single word OK and nothing else. "
            "No punctuation, no preamble, no markdown."
        ),
        allowed_tools=[],
        disallowed_tools=[
            "Bash",
            "Write",
            "Edit",
            "NotebookEdit",
            "Read",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
        ],
        model="claude-haiku-4-5-20251001",  # cheap + fast for smoke
        max_turns=1,
    )

    text_chunks: list[str] = []
    result: ResultMessage | None = None
    errored_with: str | None = None

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Say OK.")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                if msg.error:
                    errored_with = msg.error
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_chunks.append(block.text)
            elif isinstance(msg, ResultMessage):
                result = msg

    assert errored_with is None, f"assistant message error: {errored_with}"
    assert result is not None, "no ResultMessage received"
    assert result.is_error is False, (
        f"result.is_error=True, errors={getattr(result, 'errors', None)}"
    )
    assert text_chunks, "no TextBlock content received"
    combined = "".join(text_chunks).strip()
    assert "OK" in combined.upper(), f"expected OK in response, got: {combined!r}"


async def test_imports_only():
    """Sanity: the API surface we depend on actually exists. Runs always (no live call)."""
    assert ClaudeSDKClient is not None
    assert ClaudeAgentOptions is not None
    assert AssistantMessage is not None
    assert TextBlock is not None
    assert ResultMessage is not None
    # Method we use on the client:
    assert hasattr(ClaudeSDKClient, "query")
    assert hasattr(ClaudeSDKClient, "receive_response")
