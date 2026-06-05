# DQ Sentinel — 3-Minute Demo Script

Recordable screencast for the Devpost submission (Google Cloud Rapid Agent Hackathon, Fivetran track). Target length **≤ 3:00**. Record the hosted app in one browser tab; narrate live.

- **Hosted URL:** https://dq-sentinel-sjsibsau7a-uc.a.run.app
- **Recommended capture:** QuickTime / OBS screen recording at 1280×720+, system audio off, mic on.
- **Tip:** Slides (`slides.html`) can open in a second tab — cut between the live app and 2–3 slides (problem, architecture, results).

---

## Pre-stage (before recording)

Two scenarios. Pick ONE for the main take; (A) is fully automated and bullet-proof.

**Scenario A — stale data → resync (no Sheet edit, agent-resolvable, PROVEN).**
- Use a connector that hasn't had a full resync recently so `_fivetran_synced` is stale (freshness fails). At record time, `transactions` (`pitiable_flow`) was ~4500 min stale.
- Nothing to pre-break — it's genuinely stale. Just confirm: open the app, the connection picker lists it.
- The agent will diagnose stale data → propose `resync_connection` → on approval, resync refreshes timestamps → freshness passes → **resolved**.

**Scenario B — schema drift (PRD §8 #1, the headline story).**
- In the `loan_products` Google Sheet, the column header is renamed `base_apr` → `headline_apr` (already staged as a fixture).
- Seed a clean baseline FIRST (before the rename) so the drift is detectable: `uv run python -c "from dq_sentinel import bq; bq.seed_baselines('loan_products')"` against clean data.
- To reach **resolved** on camera: just before you click Approve, rename the Sheet header back to `base_apr`; the agent's resync then re-imports the corrected source → schema matches baseline → resolved. (Or narrate the diagnosis + approval and show the resync; the "resolved" frame needs the source corrected.)

---

## Shot list + narration (≈3:00)

### 0:00–0:25 — Hook (slide 1 + 2)
> "Data pipelines break silently. A column gets renamed upstream, a sync goes stale — and your dashboards are wrong before anyone notices. **DQ Sentinel** is an autonomous data-quality agent that watches Fivetran pipelines, inspects the data in BigQuery, diagnoses the root cause with Gemini, and fixes it — but never writes anything without a human's say-so."

### 0:25–0:45 — Architecture (slide 3)
> "It's a 7-step loop, not a chatbot: scan, detect, inspect, diagnose, **approve**, act, verify. Gemini 3.5 Flash does the diagnosis; Fivetran's MCP server is the only way it touches pipelines; the approval gate is structural — the model literally has no write tool until a human approves."

### 0:45–1:10 — Trigger (live app)
> "Here's the agent, running on Cloud Run." *(open hosted URL)* "I pick the `transactions` connection and hit Run scan now." *(click)*
> *(point at the live step log)* "It scans Fivetran, runs data-quality checks in BigQuery against a rolling baseline — and flags a freshness violation: this table's data is over three days stale."

### 1:10–1:45 — The gate (live app — THE money shot)
> "Now it pauses. Gemini has diagnosed the root cause — the connection is healthy but a normal incremental sync never refreshed the data — and it proposes a fix: a full re-sync. Crucially, it shows me the **exact** Fivetran tool call it wants to run, with arguments." *(point at the MCP preview)*
> "I can approve, reject, or edit the targets. Nothing gets written until I click. I'll approve."  *(click Approve)*

### 1:45–2:30 — Act + verify (live app)
> "Now — and only now — the agent executes the write through Fivetran's MCP server, then it verifies: it polls the connection until the sync completes and re-runs the exact check that failed."
> *(resolved card appears)* "Freshness went from 4,541 minutes stale to 0. Status: **resolved**. And it reports time-to-resolution split into agent time versus the sync wait — so the human-in-the-loop time is honest."

### 2:30–3:00 — Close (slide: results + impact)
> "Every run produces an incident report — what broke, the root cause, the approved action, before-and-after metrics. The approval gate means an autonomous agent you can actually trust with production pipelines. Built on Gemini, Fivetran MCP, BigQuery, and Cloud Run. Thanks for watching."

---

## Backup talking points (if asked / for the written description)
- **Structural gate:** the diagnosis model is given exactly one tool — `propose_remediation` — and zero Fivetran write tools. Writes run in separate application code only after the approval Future resolves. Verified by tests (`test_web_gate` 15/15) and a 23-agent adversarial review (0 blockers).
- **No free-form SQL:** every BigQuery check is templated; table/column names validated against an allowlist + INFORMATION_SCHEMA.
- **Diagnosis is structured:** Gemini emits a typed `propose_remediation` call (root_cause, severity, evidence[], action, targets) — no brittle JSON parsing.
- **Tech:** ADK (Agent Builder code-first) + Gemini 3.5 Flash on Vertex (location `global`), Fivetran MCP over stdio, BigQuery Python client, FastAPI + an asyncio.Future approval bridge, deployed to Cloud Run.
