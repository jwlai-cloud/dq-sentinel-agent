# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Status

Pre-implementation. The repo currently contains only `docs/PRD.md` — no source code, build system, package manifest, or tests exist yet. Treat `docs/PRD.md` as the authoritative spec; any code added should map to features defined there.

There are no build/lint/test commands yet. When introducing the first implementation, also add the commands here.

## Project: DQ Sentinel

An autonomous data-quality agent for the **Google Cloud Rapid Agent Hackathon (Fivetran Track)**, deadline **2026-06-11**. It monitors Fivetran pipelines, inspects BigQuery data, diagnoses root cause with Gemini, and remediates via Fivetran MCP — with a user approval gate before any write.

## Core Architecture (from PRD)

The agent is a **7-step loop**, not a chatbot. Each step has a fixed responsibility and data contract — when adding code, preserve the boundary:

1. **SCAN** — Fivetran MCP: `list_connections` + `get_connection_details` for each.
2. **DETECT** — Flag sync failures, schema diffs, sync delays from scan output.
3. **INSPECT** — Run parameterized BigQuery SQL on flagged tables (row count, null rate, freshness, dup, distribution).
4. **DIAGNOSE** — Gemini receives structured JSON (Fivetran metadata + DQ results + baselines), returns ranked root-cause hypothesis + severity + remediation plan.
5. **RECOMMEND + APPROVE** — Hard gate. No write tool may be invoked before explicit user approval.
6. **ACT** — Fivetran MCP write tools: `sync_connection`, `resync_connection`, `resync_tables`, `reload_connection_schema_config`.
7. **VERIFY** — Poll `get_connection_state` until sync done, re-run failed DQ checks, emit incident report (before/after metrics + time-to-resolution).

### Layering

- **Orchestration:** Google Cloud Agent Builder (Vertex AI). Fallback in PRD §11 if Agent Builder is too rigid: ADK + Gemini API direct.
- **LLM:** Gemini 3 if available by hackathon, else Gemini 2.5 Pro — model ID should be swappable in one place.
- **Tools exposed to the model:**
  - Fivetran MCP server (`fivetran/fivetran-mcp`) — 9 tools listed in PRD Appendix A. Read vs write split matters: writes go through the approval gate.
  - BigQuery — either the BQ MCP server or the BQ Python client as a custom Agent Builder tool. PRD §13 Q3 flags this as an open decision; test both.
- **Baselines:** stored in BQ table `dq_sentinel.baselines` (rolling stats per table/column), updated each successful scan. DQ checks compare against this table — do not hardcode thresholds in code, read them alongside baselines.
- **Frontend:** Mesop or Streamlit. Serves conversation UI, DQ dashboard, incident history, approval workflow.
- **Hosting:** Cloud Run (required by hackathon — must produce a hosted URL).

### Non-obvious invariants

- **Approval gate is structural, not advisory.** Any Fivetran write tool must be unreachable until the user approves a specific remediation plan emitted by step 5. Do not let Gemini call write tools directly from the diagnosis step.
- **Diagnosis input is structured JSON, not free text.** Step 4 expects the exact shape shown in PRD §6.3 (root_cause, severity, evidence[], remediation[]). Downstream code parses this — keep the schema stable.
- **Demo source is Google Sheets → Fivetran → BigQuery** so the demo can deliberately break data (PRD §8). Three sheets: `customers`, `orders`, `products`. Six pre-scripted break scenarios in PRD §8 are the acceptance scenarios for the agent's detectors.

## Scope Discipline

PRD §10 splits work into **P0 (ship or fail)**, P1, P2. Default to P0 until it is complete and polished — the timeline in §12 is tight (4 weeks, solo). When asked to add a feature, first check which tier it belongs to; push back on P2 work if P0 gaps exist.

## Open Decisions (PRD §13)

These are unresolved and will shape architecture — flag them rather than silently picking:

1. Agent Builder vs ADK (decide end of week 1).
2. Fivetran free-tier connector/sync limits.
3. BigQuery access via BQ MCP vs BQ Python client.
4. Gemini 3 availability at hackathon date.

## References

- Spec: `docs/PRD.md` — single source of truth, including Fivetran MCP tool list (Appendix A) and BQ DQ SQL templates (Appendix B).
