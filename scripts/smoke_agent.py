"""Spike smoke test for task 2.1.

Confirms the ADK McpToolset wiring works end to end without needing the Gemini
model: builds the read-only Fivetran toolset, lists the tools ADK exposes after
`tool_filter`, and asserts the write tools are NOT present (the approval-gate
invariant at the tooling layer).

Run:
    export FIVETRAN_API_KEY=$(gcloud secrets versions access latest --secret=FIVETRAN_API_KEY --project=agent-era)
    export FIVETRAN_API_SECRET=$(gcloud secrets versions access latest --secret=FIVETRAN_API_SECRET --project=agent-era)
    uv run scripts/smoke_agent.py
"""
from __future__ import annotations

import asyncio

from dq_sentinel import config
from dq_sentinel.agent import fivetran_read_toolset


async def main() -> int:
    toolset = fivetran_read_toolset()
    try:
        tools = await toolset.get_tools()
    finally:
        # Ensure the MCP subprocess is torn down.
        close = getattr(toolset, "close", None)
        if close:
            res = close()
            if asyncio.iscoroutine(res):
                await res

    names = sorted(t.name for t in tools)
    print(f"read toolset exposes {len(names)} tools:")
    for n in names:
        print("  ", n)

    read_set = set(config.FIVETRAN_READ_TOOLS)
    write_set = set(config.FIVETRAN_WRITE_TOOLS)
    exposed = set(names)

    missing = read_set - exposed
    leaked = write_set & exposed

    print("\nchecks:")
    print(f"  all read tools present:     {'PASS' if not missing else 'FAIL ' + str(missing)}")
    print(f"  no write tools leaked:      {'PASS' if not leaked else 'FAIL ' + str(leaked)}")

    return 0 if not missing and not leaked else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
