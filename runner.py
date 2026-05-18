#!/usr/bin/env python3
"""
Hyperstack Triage Agent — signal-feed loop.

Reads SIGNAL blocks from a feed (stdin, file, or named pipe), forwards each to a
long-lived Claude Agent SDK session loaded with the bundled triage skills, and
streams JSON findings back to stdout.

Block format on input:
    SIGNAL <id>
    <raw text lines...>
    END

Optional context (sticky until replaced):
    MANIFEST {"vfio_passthrough": true, "node": "h100-04", ...}

Shutdown:
    SHUTDOWN

Output:
    FINDING <signal-id>
    {...}
    {...}
    END
    READY

Requires: claude-agent-sdk + claude CLI logged in (Max plan auth — no API key).
          `pip install claude-agent-sdk`
          `npm i -g @anthropic-ai/claude-code && claude login`
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

try:
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
    )
except ImportError:
    sys.stderr.write(
        "claude-agent-sdk not installed. Run: pip install claude-agent-sdk\n"
    )
    sys.exit(2)


AGENT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = AGENT_DIR / "skills"
AGENT_MD = AGENT_DIR / "AGENT.md"

# Default-deny tool gate. Whitelist read-only inspection tools the fallback path
# needs (Read/Glob/Grep for catalog lookup). Everything else — shell, write,
# sub-agent spawn, web fetch — denied so raw feed text (attacker-controllable
# in production) cannot drive code execution.
TRIAGE_TOOL_ALLOWLIST = frozenset({"Read", "Glob", "Grep"})

# Explicit denylist as defense-in-depth alongside the callback. The CLI rejects
# these before they reach the model, so even if the callback layer regresses,
# these tools remain unreachable. Keep this list in sync as the Claude Code
# tool surface evolves.
TRIAGE_TOOL_DENYLIST = (
    "Bash",
    "BashOutput",
    "KillBash",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Task",
    "TodoWrite",
    "ExitPlanMode",
    "WebFetch",
    "WebSearch",
)


async def triage_tool_gate(tool_name, tool_input, _context):
    if tool_name in TRIAGE_TOOL_ALLOWLIST:
        return PermissionResultAllow(updated_input=tool_input)
    return PermissionResultDeny(
        message=f"tool {tool_name!r} not in triage allowlist",
    )


def build_system_prompt() -> str:
    """Compose the agent system prompt from AGENT.md and skill manifests."""
    base = AGENT_MD.read_text()
    skill_index = ["", "## Bundled skills (filesystem)", ""]
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        skill_index.append(f"- `{skill_dir.name}` — {skill_md}")
    return base + "\n".join(skill_index)


async def read_block(reader: asyncio.StreamReader) -> tuple[str, str] | None:
    """Read one SIGNAL/MANIFEST/SHUTDOWN block from the feed.

    Returns (kind, payload) or None on EOF.
    kind ∈ {"signal:<id>", "manifest", "shutdown"}.
    """
    header = await reader.readline()
    if not header:
        return None
    line = header.decode("utf-8", "replace").strip()
    if not line:
        return await read_block(reader)

    if line == "SHUTDOWN":
        return ("shutdown", "")

    if line.startswith("MANIFEST "):
        return ("manifest", line[len("MANIFEST "):])

    if line.startswith("SIGNAL "):
        sig_id = line[len("SIGNAL "):].strip()
        body: list[str] = []
        while True:
            chunk = await reader.readline()
            if not chunk:
                break
            decoded = chunk.decode("utf-8", "replace").rstrip("\n")
            if decoded.strip() == "END":
                break
            body.append(decoded)
        return (f"signal:{sig_id}", "\n".join(body))

    sys.stderr.write(f"[runner] skipping unrecognised header: {line!r}\n")
    return await read_block(reader)


def render_turn(kind: str, payload: str, manifest: str | None) -> str:
    """Render the user message sent to the agent for one feed block."""
    parts: list[str] = []
    if manifest:
        parts.append(f"CURRENT MANIFEST:\n{manifest}\n")
    if kind == "manifest":
        parts.append(f"MANIFEST {payload}")
    elif kind.startswith("signal:"):
        sig_id = kind.split(":", 1)[1]
        parts.append(f"SIGNAL {sig_id}\n{payload}\nEND")
    return "\n".join(parts)


async def stream_response(client: ClaudeSDKClient) -> None:
    """Pipe the agent's textual response to stdout, line-buffered."""
    async for event in client.receive_response():
        # claude-agent-sdk yields AssistantMessage objects with .content blocks.
        content = getattr(event, "content", None)
        if content is None:
            continue
        for block in content:
            text = getattr(block, "text", None)
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()


async def main_loop(feed: Path | None, model: str) -> int:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=build_system_prompt(),
        cwd=str(AGENT_DIR),
        # setting_sources=[] is the SECURITY-CRITICAL setting: it isolates the
        # session from ~/.claude/settings.json. Without it, user-level
        # permissions.allow (which typically grants Bash, Write, Task, etc.)
        # leaks into the triage session and overrides allowed_tools.
        setting_sources=[],
        permission_mode="default",
        # Under setting_sources=[], allowed_tools acts as a strict allowlist:
        # the CLI rejects any tool not listed before it executes, even if the
        # model attempts it.
        allowed_tools=list(TRIAGE_TOOL_ALLOWLIST),
        # Defense-in-depth: explicit denylist of known dangerous tools.
        # Belt-and-suspenders alongside the allowlist.
        disallowed_tools=list(TRIAGE_TOOL_DENYLIST),
        # can_use_tool is plumbed but does not fire under CLI 2.1.143 + SDK
        # 0.1.18 when tools are pre-allowed/denied. Kept as a no-cost extra
        # layer for future CLI/SDK versions where it may become authoritative.
        can_use_tool=triage_tool_gate,
        max_turns=12,
    )

    # Wire input feed (stdin or named file/pipe).
    if feed and str(feed) != "-":
        in_fd = os.open(str(feed), os.O_RDONLY)
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, os.fdopen(in_fd, "rb"))
    else:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    manifest: str | None = None

    async with ClaudeSDKClient(options=options) as client:
        sys.stderr.write("[runner] agent up — waiting for SIGNAL blocks on feed\n")
        while True:
            block = await read_block(reader)
            if block is None:
                sys.stderr.write("[runner] feed EOF — exiting\n")
                return 0

            kind, payload = block
            if kind == "shutdown":
                sys.stderr.write("[runner] SHUTDOWN received\n")
                await client.query("SHUTDOWN")
                await stream_response(client)
                return 0

            if kind == "manifest":
                manifest = payload
                sys.stderr.write(f"[runner] manifest updated\n")
                continue

            turn = render_turn(kind, payload, manifest)
            await client.query(turn)
            await stream_response(client)
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Hyperstack triage agent loop")
    ap.add_argument(
        "--feed",
        type=Path,
        default=None,
        help="Path to feed file/FIFO. Default: stdin.",
    )
    ap.add_argument(
        "--model",
        default=os.environ.get("TRIAGE_MODEL", "claude-haiku-4-5-20251001"),
        help="Claude model id (default: claude-haiku-4-5, env: TRIAGE_MODEL)",
    )
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        rc = asyncio.run(main_loop(args.feed, args.model))
    except KeyboardInterrupt:
        sys.stderr.write("[runner] interrupted\n")
        rc = 130
    sys.exit(rc)
