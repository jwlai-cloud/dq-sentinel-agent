"""ACT step (agent-loop step 6): execute an approved remediation.

This is the post-approval execution path. It runs ONLY after step 5 returns
"approved" with a validated `propose_remediation` payload (see diagnose.py).
The Gemini model is NOT involved here — application code maps the approved
payload to exactly one Fivetran MCP write tool and invokes it directly through
`mcp_client` (design.md D4: the approval gate is structural, not advisory).

Action → write-tool mapping (spec fivetran-integration §"Remediation execution
mapping"):
    sync_connection   -> sync_connection                 body {}
    resync_connection -> resync_connection               body {}  (full historical)
    resync_tables     -> resync_tables                   body {"schema": targets}
    reload_schema     -> reload_connection_schema_config body {"exclude_mode":"PRESERVE"}
    manual            -> no MCP call; record instructions

The Fivetran write tools take a `request_body` JSON *string*; the server passes
it straight to the live REST API (it does not validate against the bundled
OpenAPI), so the bodies below match the live `/v1/connections/...` endpoints.
"""
from __future__ import annotations

import json
from typing import Any

from dq_sentinel import mcp_client

# action -> (write tool name, request_body builder taking targets -> dict)
ACTION_TO_TOOL: dict[str, str] = {
    "sync_connection": "sync_connection",
    "resync_connection": "resync_connection",
    "resync_tables": "resync_tables",
    "reload_schema": "reload_connection_schema_config",
}


def _request_body(action: str, targets: list[str]) -> dict[str, Any]:
    """Build the Fivetran REST request body for an action.

    - sync_connection: {} (force defaults to false; on-demand sync now).
    - resync_connection: {} (omitting scope = full historical re-sync).
    - resync_tables: {"schema": targets} — for /schemas/tables/resync the body's
      "schema" field is the array of *table* names to re-sync (Fivetran names the
      per-connector namespace "schema"). Matches the bundled OpenAPI and the live
      docs. If a live call rejects it, the alternative is {"scope": {"schema": targets}}.
    - reload_schema: {"exclude_mode": "PRESERVE"} keeps existing table/column
      selection while reloading the source schema to pick up new columns.
    """
    if action == "resync_tables":
        return {"schema": targets}
    if action == "reload_schema":
        return {"exclude_mode": "PRESERVE"}
    # sync_connection / resync_connection
    return {}


def planned_call(payload: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Describe the exact Fivetran MCP write call an approval would execute.

    Used by step 5 to render the "underlying tool call (with all arguments)"
    preview required by spec diagnosis-and-remediation §"Approval gate UX".
    Returns {"tool", "arguments"} for write actions, or {"tool": None, ...} for
    action=manual.
    """
    action = payload.get("action")
    targets = payload.get("targets") or []
    if action == "manual":
        return {
            "tool": None,
            "arguments": None,
            "manual_instructions": payload.get("manual_instructions", ""),
        }
    tool = ACTION_TO_TOOL.get(action)
    if tool is None:
        raise ValueError(f"no write tool for action {action!r}")
    return {
        "tool": tool,
        "arguments": {
            "connection_id": connection_id,
            "request_body": json.dumps(_request_body(action, targets)),
        },
    }


async def act(payload: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Execute the approved remediation. Returns a structured ACT result.

    For action=manual, makes no MCP call (step 7 still re-checks whether the issue
    self-resolved). For every other action, invokes exactly one write tool via the
    write-enabled MCP session (FIVETRAN_ALLOW_WRITES=true).
    """
    action = payload.get("action")
    if action == "manual":
        return {
            "executed": False,
            "action": "manual",
            "tool": None,
            "connection_id": connection_id,
            "manual_instructions": payload.get("manual_instructions", ""),
            "note": "manual action recommended; no Fivetran write performed",
        }

    plan = planned_call(payload, connection_id)
    result = await mcp_client.call_tool(
        plan["tool"], plan["arguments"], allow_writes=True
    )
    return {
        "executed": result["ok"],
        "action": action,
        "tool": plan["tool"],
        "connection_id": connection_id,
        "targets": payload.get("targets") or [],
        "request": plan["arguments"],
        "response": result["result"],
        "is_error": result["is_error"],
    }
