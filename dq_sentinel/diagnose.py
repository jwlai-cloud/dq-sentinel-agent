"""DIAGNOSE step (agent-loop step 4) + the propose_remediation contract.

Design D3/D4: the diagnosis is NOT free JSON we parse. Gemini is given exactly
one tool — `propose_remediation` — whose parameter schema *is* the diagnosis
shape. The model calls it with structured args; we read those args off the event
stream. `propose_remediation` is an internal tool with no Fivetran side effect:
the actual write happens only on the post-approval path (step 6).
"""
from __future__ import annotations

import json
from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from dq_sentinel import config

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
Action = Literal["sync_connection", "resync_connection", "resync_tables", "reload_schema", "manual"]


def propose_remediation(
    root_cause: str,
    severity: Severity,
    evidence: list[str],
    action: Action,
    targets: list[str],
    reasoning: str,
    manual_instructions: str = "",
) -> dict[str, Any]:
    """Propose a single remediation for the diagnosed data-quality incident.

    Call this exactly once. It does NOT execute anything — it records the
    proposal for human approval.

    Args:
        root_cause: One-sentence most-likely root cause.
        severity: CRITICAL, HIGH, MEDIUM, or LOW.
        evidence: Concrete facts that support the diagnosis (cite the numbers).
        action: The remediation to propose. Use resync_tables for table-level
            data issues, reload_schema for schema drift, sync_connection for
            stale/failed syncs, manual when no Fivetran write can fix it.
        targets: Affected table names (required when action is resync_tables).
        reasoning: Why this action resolves the root cause.
        manual_instructions: Required when action is manual; else empty.
    """
    return {"status": "proposed", "action": action, "targets": targets}


VALID_ACTIONS = {"sync_connection", "resync_connection", "resync_tables", "reload_schema", "manual"}


def validate_payload(p: dict[str, Any]) -> list[str]:
    """Return a list of validation errors (spec diagnosis-and-remediation)."""
    errs: list[str] = []
    if p.get("action") not in VALID_ACTIONS:
        errs.append(f"unknown action {p.get('action')!r}")
    if p.get("action") == "resync_tables" and not p.get("targets"):
        errs.append("resync_tables requires non-empty targets")
    if p.get("action") == "manual" and not p.get("manual_instructions"):
        errs.append("manual action requires manual_instructions")
    if not p.get("root_cause"):
        errs.append("root_cause is required")
    if p.get("severity") not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
        errs.append(f"invalid severity {p.get('severity')!r}")
    return errs


_INSTRUCTION = (
    "You are the diagnosis engine of DQ Sentinel, a data-quality agent for Greedy "
    "Bank's regulatory-reporting data lake. You receive a JSON payload of Fivetran "
    "connection metadata and failed BigQuery data-quality checks. Identify the single "
    "most likely root cause that explains ALL the failed checks together, then call "
    "propose_remediation exactly once.\n"
    "Mapping guidance: a schema_mismatch with a newly added column plus a null_rate "
    "spike on the old column = a source-side column rename; the fix is reload_schema "
    "(to pick up the new column) and/or resync_tables on the affected table to backfill. "
    "A large row_count drop = data loss; propose resync_tables. A freshness violation or "
    "failed sync = propose sync_connection. If the fix is downstream (dbt, dashboards) and "
    "no Fivetran write helps, use action=manual with manual_instructions.\n"
    "Cite the actual numbers from the payload in your evidence."
)


def diagnosis_agent() -> LlmAgent:
    return LlmAgent(
        model=config.GEMINI_MODEL_ID,
        name="dq_sentinel_diagnose",
        description="Correlates pipeline metadata + DQ results into a ranked root cause.",
        instruction=_INSTRUCTION,
        tools=[propose_remediation],
    )


async def diagnose(payload: dict[str, Any], feedback: str | None = None) -> dict[str, Any] | None:
    """Run the diagnosis agent over a structured evidence payload and return the
    propose_remediation arguments (the structured diagnosis), or None if the model
    never called the tool.

    `feedback` carries a correction back to the model on a retry — either a
    validation error from a prior malformed proposal (spec diagnosis-and-remediation
    §"Parameter validation") or a user's rejection reason (spec agent-loop §"User
    rejects remediation"). It is appended to the prompt so the next attempt revises.
    """
    agent = diagnosis_agent()
    runner = InMemoryRunner(agent=agent, app_name="dq_sentinel_diagnose")
    session = await runner.session_service.create_session(
        app_name="dq_sentinel_diagnose", user_id="diag"
    )
    text = "Diagnose this incident:\n" + json.dumps(payload, indent=2, default=str)
    if feedback:
        text += "\n\nIMPORTANT — revise based on this feedback:\n" + feedback
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    proposal: dict[str, Any] | None = None
    async for event in runner.run_async(user_id="diag", session_id=session.id, new_message=msg):
        if event.content and event.content.parts:
            for part in event.content.parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name == "propose_remediation":
                    proposal = dict(fc.args)
    return proposal
