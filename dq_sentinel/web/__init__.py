"""Web layer for DQ Sentinel: a FastAPI job-API + thin polling UI over the loop.

The agent loop (dq_sentinel.loop.run_loop) is reused verbatim. The browser never
talks to the loop directly: a run is a detached asyncio task on the uvicorn event
loop, and the human approval gate (step 5) is bridged to the HTTP lifecycle with
an asyncio.Future (see runs.py). The structural approval gate is preserved — the
web `approval` callback is a drop-in for the CLI one; no Fivetran write is
reachable before the future is resolved with "approved".
"""
