## Context

Pre-implementation. Solo build, 4-week deadline (2026-06-11). Hackathon rules (verified 2026-05-20 from `rapid-agent.devpost.com/rules`) mandate Google Cloud Agent Builder + Gemini + Fivetran MCP. Prohibit services that compete with Google Cloud or Fivetran. Judging: 4 equally-weighted criteria (tech implementation, design, impact, idea quality).

Architectural pressure points surfaced in exploration:
1. Diagnosis JSON shape drifts unless forced by structured output.
2. "Autonomous agent" vs "human approval gate" reads as contradiction unless gate is architectural, not advisory.
3. DQ checks compare against `dq_sentinel.baselines` — empty on first run.
4. Sync latency from Fivetran free-tier (≥5 min, possibly 15 min) dominates wall-clock; jeopardizes 3-min demo flow and "2-min MTTR" claim.
5. Fivetran MCP transport into Agent Builder is undocumented territory.
6. BigQuery access method (MCP vs Python client) affects how DQ tool is registered.
7. Agent Builder + Vertex AI in the EU/US has cold-start and quota cliffs that hurt demo determinism.

## Goals / Non-Goals

**Goals:**
- Capture P0 architecture for the 7-step loop end-to-end.
- Make the approval gate structurally unbypassable.
- Make Gemini's diagnosis output shape stable without bespoke JSON parsing.
- Give the demo a deterministic path that survives Fivetran sync latency.
- Identify the smallest set of GCP resources, IAM grants, and external accounts to provision in week 1.
- Comply with hackathon licensing + open-source clauses.

**Non-Goals:**
- Implementing any of the above (this is design only).
- P1 features (DQ dashboard, incident export, duplicate/distribution checks).
- P2 features (webhooks, dbt impact, Slack, cost estimation).
- Multi-tenant or multi-org support.
- Authn/authz beyond what Cloud Run + IAM provide out-of-the-box.

## Decisions

### D1 — Orchestrator: Google Cloud Agent Builder (Vertex AI)

Rules require it ("powered by Gemini and Google Cloud Agent Builder"). Trade-off: less local iteration speed than ADK, steeper learning curve. Mitigation: prototype the agent loop end-to-end in week 1 with mocked tools before wiring real Fivetran/BQ in week 2.

**Alternatives considered:** ADK + Gemini API direct (rejected: would violate the "powered by ... Agent Builder" rule, even if technically Google Cloud). Vertex AI Reasoning Engine direct (rejected: AB is the named primitive in rules).

### D2 — LLM: Gemini 2.5 Pro pinned, single swappable constant

Gemini 3 not confirmed shipped by 2026-05-20. Pin 2.5 Pro now, expose as `GEMINI_MODEL_ID` constant in one config file; swap day-of if 3 ships. Reasoning depth needed (multi-signal correlation in step 4), so Pro over Flash even if latency hurts.

**Alternatives:** Gemini Flash for cost/latency (rejected: diagnosis quality on multi-signal inputs is the headline judging item). Gemini 2.0 (rejected: 2.5 Pro is the latest stable as of 2026-05-20).

### D3 — Diagnosis contract: tool-call, not parsed JSON

The model does not return a JSON blob that we parse. Instead the diagnosis step exposes a tool `propose_remediation(root_cause: str, severity: enum, evidence: list[str], action: enum[sync_connection, resync_connection, resync_tables, reload_schema, manual], targets: list[str], reasoning: str)` whose definition is the schema. Gemini calls this tool with structured args; Agent Builder validates them against the declared schema.

Effects:
- PRD §6.3 JSON shape becomes the tool's parameter schema, single source of truth.
- No bespoke parser, no shape drift.
- Approval gate naturally sits between "tool call proposed" and "tool actually executes the corresponding Fivetran MCP write" (D4).
- Diagnosis reasoning is captured in the `reasoning` field, not free-form chat output.

**Alternatives:** Gemini `responseSchema` JSON mode (rejected: still requires us to parse and route, doesn't compose with the gate as cleanly). Free-form text + regex parsing (rejected: brittle, embarrassing to demo if it breaks).

### D4 — Approval gate: structural, between two distinct tools

`propose_remediation` (D3) is **not** a Fivetran write tool. It is an internal tool whose only side effect is to render the proposal to the user and await approval. On approval, application code translates the validated args into the corresponding Fivetran MCP write tool call (`sync_connection`, `resync_tables`, etc.). On reject, the loop returns to step 4 with the rejection reason as additional context.

This makes the gate unbypassable: Gemini physically cannot invoke a Fivetran write tool directly because those tools are not registered in its tool set. They are registered only on the post-approval execution path.

**Alternatives:** "Soft" gate where Gemini has write tools but is prompted not to call them (rejected: PRD calls out the gate as structural — soft gates fail under prompt injection or model drift). HITL via Agent Builder's built-in approval UI (preferred where AB supports it; if not, render via frontend with a callback).

### D5 — BigQuery access: BQ Python client as Agent Builder custom tool

Wrap BQ queries (PRD Appendix B + baseline reads/writes) in a Python function exposed as an Agent Builder custom tool. Tool parameters are bound (table name, column name, threshold) — no free-form SQL from the model. This prevents SQL injection and lets us pre-validate against `INFORMATION_SCHEMA`.

**Alternatives:** BQ MCP server (rejected for solo P0: adds a second MCP integration to debug; revisit for P1). Free-form SQL tool taking model-authored SQL (rejected: injection + cost runaway risk + arbitrary writes).

### D6 — Baselines: explicit `seed_baselines` scan as step 0

Before the 7-step loop runs against broken data, an explicit `seed_baselines` operation runs once against the clean source-of-truth Sheets data and writes row counts, per-column null rates, and schema snapshot to `dq_sentinel.baselines`. The agent loop refuses to run if no baseline exists for a connection (returns "baseline missing, run seed first" rather than silently passing).

This makes the cold-start problem visible instead of latent. Demo script: seed → break → run loop.

**Alternatives:** Implicit baseline on first scan (rejected: silent no-op on first run, exact opposite of what a DQ agent should do). Hardcoded thresholds (rejected: PRD calls for rolling baselines; hardcoding contradicts the spec).

### D7 — Demo strategy: pre-stage + manual sync trigger

The demo cannot wait through two 15-min sync intervals. Pre-stage: break is applied to the Sheet *before* recording starts. Demo opens with the loop already detecting a known-bad state. Remediation step invokes `sync_connection` immediately (Fivetran honors on-demand sync — verify in week 1) to skip the next-interval wait. Demo video narrates: "detection + diagnosis + remediation in seconds; wall-clock dominated by sync latency."

If on-demand sync is gated on free tier: fall back to "before/after screenshots" pattern in the video while the agent's reasoning trace plays live.

**Alternatives:** Live break during demo (rejected: ≥5 min dead air). Mock Fivetran responses in demo (rejected: violates the spirit of "functional agent" requirement).

### D8 — Open-source compliance: Apache-2.0

OSI-approved, commercial-use unrestricted (required by rules), patent grant (matters because we expose agent reasoning that may touch patented data-quality methods). LICENSE file at repo root + license set in GitHub About so it renders in the repo sidebar (rules require "detectable and visible").

**Alternatives:** MIT (rejected: no patent grant; same code clarity but slightly worse for hackathon judges + Google's own licensing preference is Apache-2.0). GPL/AGPL (rejected: copyleft burdens reuse and downstream commercial use, against rules' spirit).

## Risks / Trade-offs

- **Agent Builder learning curve consumes week 1** → mitigate by following the `agent-starter-pack` template (`github.com/GoogleCloudPlatform/agent-starter-pack`) end-to-end on day 1, before touching Fivetran/BQ.
- **Fivetran MCP doesn't speak Agent Builder's transport natively** → spike day 2: stand up the MCP server, confirm AB can register it (likely via Reasoning Engine custom tool wrapper if direct MCP isn't supported). If blocked, wrap the MCP tools as plain Python functions calling MCP via stdio subprocess.
- **Free-tier Fivetran sync interval too long for `sync_connection` to feel instant** → verify week 1; D7 fallback covers if so.
- **Gemini 2.5 Pro tool-call latency on 9 Fivetran tools + 1 BQ tool + 1 proposal tool may be slow** → cap tool count visible to the model per step (only register the tools relevant to that step in the AB orchestration graph).
- **`dq_sentinel.baselines` schema migrates as we add checks** → ship initial schema with a `metric_version` column; future checks add rows with new versions, no DDL needed.
- **Single GCP project for demo + dev** → cheap and simple; risk is accidental quota burn. Mitigation: hard-set BQ query cost cap via custom quota.
- **License field on GitHub About requires standard LICENSE filename + recognized SPDX text** → use the verbatim Apache-2.0 text, no modifications.

## Migration Plan

Greenfield — no rollback. Sequencing:

1. **Repo bootstrap (this change):** LICENSE, README, OpenSpec artifacts.
2. **Spike (week 1):** Agent Builder hello-world via starter-pack; Fivetran MCP standalone; Sheets→Fivetran→BQ pipeline live.
3. **Capability implementations (weeks 2–3):** one PR per capability in proposal § Capabilities, in order (fivetran-integration → bigquery-dq-checks → agent-loop → diagnosis-and-remediation).
4. **Demo + ship (week 4):** Cloud Run deploy, video recording, Devpost submission.

If a P0 capability is at risk in week 3, drop scope to the single end-to-end "schema drift + null spike" scenario from PRD §8 and ship that. Don't cut the approval gate or the verify step — they are the headline judging items.

## Open Questions

1. **Fivetran free-tier on-demand `sync_connection` allowed?** Verify week 1 day 1.
2. **Does Agent Builder register MCP servers directly, or do we need a wrapper?** Verify week 1 day 2.
3. **GitHub repo public from day 1 or stay private until week 3?** Default: public from day 1 (rules require public for submission; nothing private worth hiding).
4. **Frontend: Mesop vs Streamlit?** Defer to week 3; Agent Builder's bundled chat UI carries weeks 1–2.
5. **Gemini 3 ship date** — monitor; if it ships before 2026-06-08, swap `GEMINI_MODEL_ID` and re-test diagnosis quality on the 6 break scenarios.
