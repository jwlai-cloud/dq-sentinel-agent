"""Direct Fivetran MCP client for application code (no LLM in the loop).

Steps 1-5 reach Fivetran through ADK's `McpToolset` so the *model* can call read
tools. The post-approval write path (step 6) and the verification poll (step 7)
must NOT go through the model — the approval gate is structural (design.md D4):
application code, not Gemini, invokes write tools. This module is that path. It
opens a short-lived stdio session to the same `fivetran-mcp` server and calls a
tool by name with explicit arguments.

The server's `FIVETRAN_ALLOW_WRITES` env var is the second gate layer: callers
that only read (e.g. step 7 polling) open the session with allow_writes=False.

`schema_file` quirk (see memory fivetran-mcp-usage): every tool requires a
`schema_file` argument equal to a fixed path string. The path is NOT mechanically
derivable from the tool name, so we read it off the tool's own inputSchema
(default/const/enum) at call time rather than hardcoding guesses.
"""
from __future__ import annotations

import contextlib
import json
import re
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dq_sentinel import config


@contextlib.asynccontextmanager
async def _session(*, allow_writes: bool) -> AsyncIterator[ClientSession]:
    params = StdioServerParameters(
        command=config.FIVETRAN_MCP_COMMAND,
        args=config.FIVETRAN_MCP_ARGS,
        env=config.fivetran_env(allow_writes=allow_writes),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


_SCHEMA_FILE_RE = re.compile(r"(open-api-definitions/[A-Za-z0-9_./-]+\.json)")


def _schema_file_for(input_schema: dict[str, Any]) -> str | None:
    """Extract the required `schema_file` value from a tool's inputSchema.

    The Fivetran MCP server does not pin the path via const/default/enum; it only
    states it in the property's description (e.g. "...read the schema file at
    'open-api-definitions/connections/connection_state.json'..."). The path is
    not mechanically derivable from the tool name (get_connection_state maps to
    connection_state.json), so we parse it out of the description.
    """
    prop = (input_schema or {}).get("properties", {}).get("schema_file")
    if not isinstance(prop, dict):
        return None
    for key in ("const", "default"):
        if isinstance(prop.get(key), str):
            return prop[key]
    enum = prop.get("enum")
    if isinstance(enum, list) and enum and isinstance(enum[0], str):
        return enum[0]
    m = _SCHEMA_FILE_RE.search(prop.get("description", "") or "")
    return m.group(1) if m else None


async def tool_schemas(*, allow_writes: bool = False) -> dict[str, dict[str, Any]]:
    """Map of tool name -> inputSchema for every tool the server exposes."""
    async with _session(allow_writes=allow_writes) as s:
        resp = await s.list_tools()
        return {t.name: (t.inputSchema or {}) for t in resp.tools}


def _content_to_obj(result: Any) -> Any:
    """Best-effort decode of an MCP CallToolResult into plain Python.

    Fivetran tools return their JSON payload as a text content block; parse it
    when possible, else fall back to the concatenated text.
    """
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    raw = "\n".join(parts)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


async def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    allow_writes: bool,
) -> dict[str, Any]:
    """Call a Fivetran MCP tool by name, auto-filling `schema_file`.

    Returns {"ok", "is_error", "tool", "arguments", "result"}.
    """
    async with _session(allow_writes=allow_writes) as s:
        resp = await s.list_tools()
        schema = next((t.inputSchema for t in resp.tools if t.name == name), None)
        if schema is None:
            raise ValueError(
                f"tool {name!r} not exposed by server "
                f"(allow_writes={allow_writes}); is it write-gated?"
            )
        args = dict(arguments)
        if "schema_file" not in args:
            sf = _schema_file_for(schema)
            if sf:
                args["schema_file"] = sf
        result = await s.call_tool(name, args)
        return {
            "ok": not getattr(result, "isError", False),
            "is_error": bool(getattr(result, "isError", False)),
            "tool": name,
            "arguments": args,
            "result": _content_to_obj(result),
        }
