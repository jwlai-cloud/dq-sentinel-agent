# Devpost form — copy/paste cheat-sheet

Field-by-field values for the Devpost submission. Hosted URL:
https://dq-sentinel-sjsibsau7a-uc.a.run.app · Repo: https://github.com/jwlai-cloud/dq-sentinel-agent

---

## Project name
DQ Sentinel

## Elevator pitch (≤200)
Autonomous data-quality agent that watches Fivetran pipelines, diagnoses breakages with Gemini, and fixes them in BigQuery — with a structural human-approval gate before any write.

## Thumbnail
docs/demo/img/thumbnail.png  (2400×1600, 3:2)

---

## About the project  (paste the block below into the "About the project" textarea)

## Inspiration
Data pipelines fail quietly. A column gets renamed in a source system, a sync goes stale, rows disappear — and the dashboards downstream are wrong long before anyone notices. The usual "fix" is a human paging through logs at 2am. We wanted an agent that does the watching, the diagnosis, and the repair — but one a data team can actually trust near production, because it never changes a pipeline without explicit human approval.

## What it does
DQ Sentinel is an autonomous data-quality agent for Fivetran → BigQuery. It runs a fixed **7-step loop**:

1. **Scan** — lists Fivetran connections and their status via the Fivetran MCP server.
2. **Detect** — flags sync failures, schema drift, and staleness.
3. **Inspect** — runs parameterized BigQuery checks (row count, null rate, freshness, schema) against a rolling baseline.
4. **Diagnose** — Gemini 3.5 Flash correlates the signals into a ranked root cause and a typed remediation proposal.
5. **Approve** — a hard, structural human gate: it shows the **exact** Fivetran tool call it wants to run, with arguments, and waits.
6. **Act** — on approval, executes exactly one Fivetran write (sync / resync / reload schema).
7. **Verify** — polls until the sync completes, re-runs the checks that failed, and emits an incident report with before/after metrics and time-to-resolution.

## How we built it
- **Agent:** Google ADK (the code-first arm of Agent Builder), deployed on Cloud Run.
- **LLM:** Gemini 3.5 Flash on Vertex AI. The diagnosis step gives the model exactly one tool — `propose_remediation` — whose typed parameters *are* the diagnosis schema, so there is no brittle JSON parsing.
- **Pipelines:** the official `fivetran/fivetran-mcp` server over stdio. Read tools are exposed to the model; the four write tools are invoked only by application code.
- **Data:** BigQuery via the Python client. Every check is a templated query; table and column names are validated against an allowlist + `INFORMATION_SCHEMA` — no free-form SQL ever reaches BigQuery.
- **Web:** FastAPI + a thin polling UI. The approval gate is bridged to the HTTP request lifecycle with an `asyncio.Future`: a run is a detached task, the `approval` callback parks on a Future, and a POST resolves it — so no request thread is held across the human wait or the multi-minute verify poll.
- **Demo data:** Google Sheets → Fivetran → BigQuery, so issues can be staged deliberately.

## Challenges we ran into
- **Reconciling a long agent loop with the web request lifecycle** — the loop awaits a human mid-flight, then polls Fivetran for minutes. Solved with a detached-task + `asyncio.Future` bridge, so no request thread is held across either wait.
- **Fivetran semantics:** `get_connection_state` returns HTTP 405 on the live API (we poll `get_connection_details` instead), and a *normal* sync of an unchanged Google Sheet doesn't rewrite `_fivetran_synced` — only a full **resync** does — which the diagnosis now reflects.
- **Cloud Run footguns:** background CPU must stay allocated (`--no-cpu-throttling`) or the detached task silently freezes; and the Google Front End intercepts a bare `/healthz`, so the health route lives at `/api/health`.

## Accomplishments that we're proud of
- A **structural** approval gate: the diagnosis model has zero Fivetran write tools in scope — it physically cannot sync, resync, or reload. The write runs in separate code only after the approval Future resolves, and the UI shows the precise MCP call first. It survives prompt injection and model drift because the capability simply isn't there.
- A full RESOLVED loop proven live, end-to-end: a stale connector (freshness 4541 min) → Gemini diagnosed → approved → real Fivetran resync → re-check **4541 → 0** → resolved, in ~3 min (agent time 2m34s, sync wait 37s).
- 57 automated checks green (loop 26 · gate bridge 15 · HTTP 16); the gate held under a 23-agent adversarial review with 0 blockers.

## What we learned
- For an agent that touches production, a **structural** guardrail (the tool isn't in scope) beats a prompt-based one ("please don't") — it's verifiable and can't drift.
- Real connectors have surprising semantics (a no-op sync doesn't refresh timestamps; a "get state" endpoint that 404/405s) — grounding the LLM's diagnosis in the *actual* behavior matters more than a clean abstraction.
- Bridging a long-running, human-in-the-loop agent to a stateless web platform is the real engineering: the `asyncio.Future` gate + the Cloud Run CPU/health gotchas were where the time went.

## What's next for DQ Sentinel
Firestore-backed incident history, a richer DQ dashboard, duplicate and distribution-shift checks, and scheduled (not just manual) triggers.

---

## Built with
google-adk, gemini, vertex-ai, fivetran, mcp, bigquery, fastapi, cloud-run, python

## "Try it out" links
- https://dq-sentinel-sjsibsau7a-uc.a.run.app
- https://github.com/jwlai-cloud/dq-sentinel-agent

## Image gallery (upload, 3:2 best)
- docs/demo/img/thumbnail.png   (hero card)
- docs/demo/img/gate.png        (the approval gate)
- docs/demo/img/resolved.png    (verified incident report)
- docs/demo/img/landing.png     (the dashboard)

## Video demo link
(add the YouTube/Vimeo URL after upload)
