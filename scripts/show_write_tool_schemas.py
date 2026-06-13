"""Introspect the Fivetran MCP write tools + get_connection_state.

Read-only: lists tool inputSchemas so we can wire step 6 (ACT) with the exact
argument names and the required `schema_file` path per tool. NO write tool is
invoked here. Run with FIVETRAN_ALLOW_WRITES enabled so the write tools are
visible to list_tools.

Run:
    export FIVETRAN_API_KEY=$(gcloud secrets versions access latest --secret=FIVETRAN_API_KEY --project=agent-era)
    export FIVETRAN_API_SECRET=$(gcloud secrets versions access latest --secret=FIVETRAN_API_SECRET --project=agent-era)
    uv run scripts/show_write_tool_schemas.py
"""
from __future__ import annotations

import asyncio
import json

from dq_sentinel import config
from dq_sentinel.mcp_client import _schema_file_for, tool_schemas

WANT = config.FIVETRAN_WRITE_TOOLS + ["get_connection_state"]


async def main() -> int:
    schemas = await tool_schemas(allow_writes=True)
    for name in WANT:
        schema = schemas.get(name)
        print(f"\n===== {name} =====")
        if schema is None:
            print("  NOT EXPOSED (still write-gated?)")
            continue
        print(f"  schema_file -> {_schema_file_for(schema)!r}")
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        for pname, p in props.items():
            req = "REQUIRED" if pname in required else "optional"
            ptype = p.get("type", p.get("anyOf", "?"))
            print(f"  - {pname} ({ptype}, {req})")
        # full schema for the two tricky ones
        if name in ("resync_tables", "reload_connection_schema_config"):
            print("  full inputSchema:")
            print(json.dumps(schema, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
