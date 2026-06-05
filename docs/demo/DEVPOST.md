# DQ Sentinel — Devpost submission

**Track:** Fivetran · **Hosted URL:** https://dq-sentinel-sjsibsau7a-uc.a.run.app · **Repo:** https://github.com/jwlai-cloud/dq-sentinel-agent

---

## Inspiration
Data pipelines fail quietly. A column gets renamed in a source system, a sync goes stale, rows disappear — and the dashboards downstream are wrong long before anyone notices. The usual "fix" is a human paging through logs at 2am. We wanted an agent that does the watching, the diagnosis, and the repair — but that a data team can actually trust near production, because it never changes a pipeline without explicit human approval.

## What it does
DQ Sentinel is an autonomous data-quality agent for Fivetran → BigQuery. It runs a fixed **7-step loop**:

1. **Scan** — lists Fivetran connections + status via the Fivetran MCP server.
2. **Detect** — flags sync failures, schema drift, and staleness.
3. **Inspect** — runs parameterized BigQuery checks (row count, null rate, freshness, schema) against a rolling baseline.
4. **Diagnose** — Gemini 3.5 Flash correlates the signals into a ranked root cause and a typed remediation proposal.
5. **Approve** — a hard, structural human gate: it shows the exact Fivetran tool call it wants to run and waits.
6. **Act** — on approval, executes exactly one Fivetran write (sync / resync / reload schema).
7. **Verify** — polls until the sync completes, re-runs the failed checks, and emits an incident report with before/after metrics and time-to-resolution.

## How we built it
- **Agent:** Google ADK (the code-first arm of Agent Builder), deployed on Cloud Run.
- **LLM:** Gemini 3.5 Flash on Vertex AI (served from `global`). The diagnosis step gives the model exactly one tool — `propose_remediation` — whose typed parameters *are* the diagnosis schema, so there's no brittle JSON parsing.
- **Pipelines:** the official `fivetran/fivetran-mcp` server over stdio. Read tools (list/get) are exposed to the model; the four write tools are pre-installed in the container and invoked only by application code.
- **Data:** BigQuery via the Python client. Every check is a templated query; table and column names are validated against an allowlist + `INFORMATION_SCHEMA` — no free-form SQL ever reaches BigQuery.
- **Web:** FastAPI + a thin vanilla-JS polling UI. The approval gate is bridged to the HTTP request lifecycle with an `asyncio.Future`: a run is a detached task, the `approval` callback parks on a Future, and a POST resolves it — so no request thread is held across the human wait or the multi-minute verify poll.
- **Demo data:** Google Sheets → Fivetran → BigQuery (`account_holders`, `transactions`, `loan_products`) so issues can be staged deliberately.

## The thing we're proudest of: a *structural* approval gate
"Autonomous agent" and "human approval" sound contradictory. We made the gate structural instead of a polite prompt: the diagnosis model has **zero** Fivetran write tools in scope — it physically cannot sync, resync, or reload. The write runs in separate application code that is only reachable after the approval Future resolves with "approved", and the UI shows the precise MCP call (with arguments) before you click. It survives prompt injection and model drift because the capability simply isn't there.

## Challenges we ran into
- **Reconciling a long agent loop with the web request lifecycle** — the loop awaits a human mid-flight, then polls Fivetran for minutes. Solved with the detached-task + `asyncio.Future` bridge (no thread held across either wait).
- **Fivetran semantics:** `get_connection_state` returns HTTP 405 live (we poll `get_connection_details` instead), and a *normal* sync of an unchanged Google Sheet doesn't rewrite `_fivetran_synced` — only a full **resync** does. The agent's diagnosis reflects this: stale data → `resync_connection`.
- **Cloud Run footguns:** background CPU must stay allocated (`--no-cpu-throttling`) or the detached task silently freezes; and the GFE intercepts a bare `/healthz`, so the health route lives at `/api/health`.

## Accomplishments
- A full RESOLVED loop proven live end-to-end: a stale connector (freshness 4541 min) → Gemini diagnosed → approved → real Fivetran resync → re-check **4541 → 0** → resolved, in ~3 min wall-clock (agent time 2m34s, sync wait 37s).
- 57 automated checks green (loop 26 · gate bridge 15 · HTTP 16); the gate held under a 23-agent adversarial review with 0 blockers.

## What's next
Firestore-backed incident history, a richer dashboard, duplicate/distribution checks, and scheduled (not just manual) triggers.

## Built with
`google-adk` · Gemini 3.5 Flash · Vertex AI · Fivetran MCP · BigQuery · FastAPI · Cloud Run · Python
