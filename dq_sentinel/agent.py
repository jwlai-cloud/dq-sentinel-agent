"""ADK agent wiring for DQ Sentinel.

This is the spike-stage agent (PRD week-1 task 2.1): a single LlmAgent that can
read Fivetran pipeline health via the Fivetran MCP server. The full 7-step loop,
the approval gate, and the write path land in later changes.

The Fivetran MCP is consumed via ADK's McpToolset over stdio, with `tool_filter`
restricting the model to read-only tools (design.md D1/D4). A write-enabled
toolset is provided by a separate factory for the post-approval step.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from dq_sentinel import config


def _fivetran_toolset(*, allow_writes: bool, tool_filter: list[str]) -> McpToolset:
    """Construct an McpToolset bound to the Fivetran MCP server.

    Two gate layers (design.md D4):
      1. tool_filter — the model only sees the listed tools.
      2. FIVETRAN_ALLOW_WRITES — the server refuses write tools when False.
    """
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=config.FIVETRAN_MCP_COMMAND,
                args=config.FIVETRAN_MCP_ARGS,
                env=config.fivetran_env(allow_writes=allow_writes),
            ),
            timeout=120,
        ),
        tool_filter=tool_filter,
    )


def fivetran_read_toolset() -> McpToolset:
    """Read-only Fivetran toolset for agent-loop steps 1-5."""
    return _fivetran_toolset(allow_writes=False, tool_filter=config.FIVETRAN_READ_TOOLS)


def fivetran_write_toolset() -> McpToolset:
    """Write-enabled Fivetran toolset for the post-approval step 6 only."""
    return _fivetran_toolset(allow_writes=True, tool_filter=config.FIVETRAN_WRITE_TOOLS)


# Spike agent: scan + report pipeline health. Read-only.
root_agent = LlmAgent(
    model=config.GEMINI_MODEL_ID,
    name="dq_sentinel_scanner",
    description="Scans Fivetran pipelines and reports their health.",
    instruction=(
        "You are DQ Sentinel, a data-quality engineer for Greedy Bank. "
        "When asked to scan, call list_connections (the schema_file argument is "
        "'open-api-definitions/connections/list_connections.json'). Summarise each "
        "connection's sync_state, setup_state, and any warnings. Flag anything that "
        "is failed, broken, delayed, or warning. Do not attempt any write or fix — "
        "this build only scans and reports."
    ),
    tools=[fivetran_read_toolset()],
)
