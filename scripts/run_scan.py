"""Spike hello-world for task 2.1: drive the LlmAgent so Gemini actually calls
the Fivetran MCP `list_connections` tool and reports pipeline health.

Run:
    export FIVETRAN_API_KEY=$(gcloud secrets versions access latest --secret=FIVETRAN_API_KEY --project=agent-era)
    export FIVETRAN_API_SECRET=$(gcloud secrets versions access latest --secret=FIVETRAN_API_SECRET --project=agent-era)
    export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=agent-era GOOGLE_CLOUD_LOCATION=us-central1
    uv run scripts/run_scan.py
"""
from __future__ import annotations

import asyncio

from google.adk.runners import InMemoryRunner
from google.genai import types

from dq_sentinel.agent import root_agent

PROMPT = "Scan all Fivetran connections and report each one's sync state and any warnings."


async def main() -> int:
    runner = InMemoryRunner(agent=root_agent, app_name="dq_sentinel_spike")
    session = await runner.session_service.create_session(
        app_name="dq_sentinel_spike", user_id="spike"
    )
    content = types.Content(role="user", parts=[types.Part(text=PROMPT)])

    final = ""
    async for event in runner.run_async(
        user_id="spike", session_id=session.id, new_message=content
    ):
        if event.content and event.content.parts:
            for p in event.content.parts:
                if getattr(p, "function_call", None):
                    print(f"[tool call] {p.function_call.name}({dict(p.function_call.args)})")
                if getattr(p, "function_response", None):
                    print(f"[tool result] {p.function_response.name} -> (received)")
        if event.is_final_response() and event.content:
            final = "".join(p.text or "" for p in event.content.parts)

    print("\n=== agent final response ===")
    print(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
