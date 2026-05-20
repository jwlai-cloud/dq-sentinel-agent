## Why

Repo is pre-implementation. PRD (`docs/PRD.md`) defines an autonomous data-quality agent for the Google Cloud Rapid Agent Hackathon (Fivetran track, deadline 2026-06-11 14:00 PDT). To ship in ≤4 weeks solo we need the structural decisions captured before any code lands — chiefly that Gemini's diagnosis output is modeled as proposed tool calls (not parsed JSON) and that the human approval gate sits between proposal and execution in Agent Builder. This change establishes the P0 architecture, capability boundaries, and week-by-week tasks; later changes deliver P1/P2.

## What Changes

- Lock orchestration on **Google Cloud Agent Builder** (Vertex AI). Hackathon rules require it ("powered by Gemini and Google Cloud Agent Builder"). ADK fallback in PRD §11 is dropped.
- Lock LLM on **Gemini 2.5 Pro** with a single swappable model-ID constant; upgrade to Gemini 3 only if it ships before submission.
- Lock Fivetran integration on **Fivetran MCP server** (`fivetran/fivetran-mcp`) — required by Fivetran track rules; REST fallback dropped.
- Lock BigQuery access on the **BigQuery Python client wrapped as an Agent Builder custom tool** (BQ MCP option deferred — fewer moving parts for a solo build).
- Diagnosis contract changes from "Gemini returns JSON, we parse" to **"Gemini returns a proposed tool call, Agent Builder pauses for approval, then executes"**. PRD §6.3 schema becomes the tool-arg schema, not a free JSON blob.
- Introduce explicit **baseline seeding** as scan #0 of the agent loop, because cold-start DQ checks compare against an empty `dq_sentinel.baselines` and would silently no-op.
- Adopt **Apache-2.0 LICENSE** (OSI-approved, commercial-use unrestricted, patent grant) at repo root + populate GitHub About license field to satisfy the visibility requirement.
- Repo will live at GitHub under name `dq-sentinel-agent`.
- Frontend: defer Mesop vs Streamlit pick to week 3; Agent Builder UI hosts the conversation in week 2.

Non-goals for this change: implementing any of the above; P1 dashboard/incident export; P2 webhooks/dbt/Slack.

## Capabilities

### New Capabilities

- `agent-loop`: 7-step orchestration (scan → detect → inspect → diagnose → recommend+approve → act → verify) in Agent Builder, including the structural human-in-loop gate between step 5 and step 6.
- `fivetran-integration`: Wiring of Fivetran MCP read tools (`list_connections`, `get_connection_details`, `get_connection_state`, `get_connection_schema_config`) and write tools (`sync_connection`, `resync_connection`, `resync_tables`, `reload_connection_schema_config`) into Agent Builder, with the read/write split enforcing the approval gate.
- `bigquery-dq-checks`: P0 DQ check library (row count, null rate, freshness) executed via BQ Python client tool, plus the `dq_sentinel.baselines` storage contract and the scan-#0 seeding behavior.
- `diagnosis-and-remediation`: Gemini-driven root-cause hypothesis emitted as a proposed Fivetran write tool call with reasoning trace, severity, and evidence; covers the approval-gate semantics, post-execution polling, and incident report shape.

### Modified Capabilities

None (greenfield).

## Impact

- **Code/repo:** Greenfield — repo becomes a Python project. New files: `LICENSE` (Apache-2.0), `README.md` (stub with hosted URL, repo URL, license badge), agent code under a top-level package once specs land.
- **Cloud:** New GCP project for Vertex AI + BQ. Cloud Run for hosted demo URL. Secret Manager for Fivetran API key.
- **External accounts:** Fivetran free-tier account, Google Sheets demo source, GitHub public repo, Devpost submission.
- **Open decisions resolved:** PRD §13 Q1 (AB chosen), Q3 (BQ Python client chosen), Q4 (Gemini 2.5 Pro pinned).
- **Open decisions still live:** PRD §13 Q2 (Fivetran free-tier limits — verify in week 1), Q5 (solo confirmed; team option closed).
- **Compliance:** No Snowflake/Databricks/Airbyte (would violate "compete with Partner/Google Cloud" clause). Apache-2.0 satisfies OSI + commercial-use requirements in §Open-Source Clauses.
