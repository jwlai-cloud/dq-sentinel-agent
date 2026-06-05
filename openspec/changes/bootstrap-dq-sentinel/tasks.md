## 1. Repo + Cloud Bootstrap (Week 1, days 1-2)

- [x] 1.1 Create `LICENSE` (Apache-2.0 verbatim) at repo root
- [x] 1.2 Create `README.md` stub with project name, one-liner, hosted URL placeholder, repo URL placeholder, license badge, hackathon track callout
- [x] 1.3 `git init`, first commit, push to GitHub `dq-sentinel-agent` (public), set License field in repo About so it renders in sidebar — https://github.com/jwlai-cloud/dq-sentinel-agent
- [x] 1.4 Use existing GCP project `agent-era` (region `us-central1`); enable `aiplatform`, `bigquery`, `secretmanager`, `run`, `cloudbuild`, `iam` APIs
- [x] 1.5 Provision BQ dataset `agent-era.dq_sentinel` in `us-central1`; create `baselines` table (PARTITION BY DATE(captured_at), CLUSTER BY connection_id, table_name, metric) per spec `bigquery-dq-checks` §"Baseline storage contract"
- [ ] 1.6 Create Fivetran free-tier account; confirm whether on-demand `sync_connection` is allowed on free tier (resolves Open Question 1 in design.md)
- [ ] 1.7 Stand up Sheets → Fivetran → BQ for `customers`, `orders`, `products` sheets (PRD §8)
- [ ] 1.8 Store Fivetran API key in Secret Manager as `FIVETRAN_API_KEY` in project `agent-era`

## 2. Agent Builder + Fivetran MCP Spike (Week 1, days 3-5)

- [x] 2.1 ADK hello-world end-to-end — DONE 2026-06-02. Lean hand-rolled ADK project (`dq_sentinel/{config,agent}.py`, not the starter-pack) instead of agent-starter-pack (fewer files, full control). Gemini 3.5 Flash → ADK `McpToolset` (read-only `tool_filter`) → Fivetran MCP → live `list_connections` → coherent health report. Auth via runtime SA `dq-sentinel-runtime@agent-era` (key in `.secrets/`, gitignored; same SA for Cloud Run later). KEY GOTCHA: Gemini 3.x served from Vertex location `global`, not `us-central1` (regional → 403). Wiring smoke (`scripts/smoke_agent.py`) proves tool_filter exposes exactly the 5 read tools, zero write tools leaked.
- [x] 2.2 Stand up Fivetran MCP server (`fivetran/fivetran-mcp`) standalone; confirm `list_connections` returns the live connections — DONE 2026-06-02. `uvx --from git+https://github.com/fivetran/fivetran-mcp fivetran-mcp`, server v1.27.2, 77 tools (all 9 PRD Appendix A tools present), auth via `FIVETRAN_API_KEY`+`FIVETRAN_API_SECRET` (two separate env vars — NOT the combined base64 blob). Returns full status payload (setup_state, sync_state, schema_status, warnings[], schedule). Quirk: every tool requires a `schema_file` arg = a fixed path string the caller must pass to confirm it read the OpenAPI def (e.g. `open-api-definitions/connections/list_connections.json`).
- [ ] 2.3 Spike: register Fivetran MCP into Agent Builder. Decide between direct MCP support vs Python-subprocess wrapper (resolves Open Question 2 in design.md). NOTE: MCP exposes all 77 tools at once; the structural approval gate (design D4) needs us to surface only read tools to Gemini in steps 1-5. Lever found: `FIVETRAN_ALLOW_WRITES=false` env var disables all write tools at the server level — run a read-only MCP instance for steps 1-5, a write-enabled path only for step 6.
- [x] 2.4 Pin `GEMINI_MODEL_ID = "gemini-3.5-flash"` in a single config module (`dq_sentinel/config.py`) — DONE. Verified available + callable on Vertex at location `global` (not us-central1).
- [x] 2.5 Demo break scenario #1 (schema rename) — DONE 2026-06-02. Renamed `base_apr`→`headline_apr` in the loan_products sheet, synced. Result in BQ: both columns present, `base_apr` 100/100 NULL, `headline_apr` 0/100 NULL, values migrated exactly — textbook PRD scenario 1. FINDING: Fivetran `get_connection_schema_config` for a Sheets connector returns a thin payload (no column-level drift detail); the reliable schema-drift signal is **BQ `INFORMATION_SCHEMA.COLUMNS`** (per the `bigquery-dq-checks` schema-mismatch check). loan_products table currently left in the broken state as a test fixture for building the detectors. (loan_products Fivetran connection id = `subjected_synthesis`.)

## 3. Capability: `fivetran-integration` (Week 2, days 1-3)

- [ ] 3.1 Register all four read tools (`list_connections`, `get_connection_details`, `get_connection_state`, `get_connection_schema_config`) into Agent Builder for pre-approval steps
- [x] 3.2 Application-side write path — `dq_sentinel/mcp_client.py` talks to the Fivetran MCP directly (no LLM): short-lived stdio session, auto-fills the `schema_file` arg by regex-parsing it from each tool's inputSchema description (it is NOT pinned via const/default, and is NOT derivable from the tool name — `get_connection_state`→`connection_state.json`). Write tools reached only via `allow_writes=True` sessions.
- [x] 3.3 action→write-tool routing — `dq_sentinel/act.py` `ACTION_TO_TOOL` + `_request_body`. Each Fivetran write tool takes a `request_body` JSON *string* the server passes straight to the live REST API (no schema validation — confirmed by reading server.py). Bodies: sync_connection `{}`, resync_connection `{}` (full historical), resync_tables `{"schema": targets}` (the `/schemas/tables/resync` body's `schema` field holds *table* names), reload_schema `{"exclude_mode":"PRESERVE"}`. `planned_call()` renders the exact tool+args preview for the gate UI.
- [x] 3.4 Model cannot call write tools — structural: Gemini is invoked ONLY in step 4 (diagnose.py, tool=propose_remediation). The loop (loop.py) never registers a Fivetran write tool with any model; writes go through app code (act.py). Reinforced by smoke_agent (read toolset leaks 0 write tools) + `FIVETRAN_ALLOW_WRITES=false` on read sessions.

## 4. Capability: `bigquery-dq-checks` (Week 2, days 4-5)

- [x] 4.1 `dq_check_row_count` (dq_sentinel/bq.py) — vs baseline, >30% deviation fails. Verified.
- [x] 4.2 `dq_check_null_rate` — vs baseline, >2x fails (any-null fails when baseline=0). Verified: base_apr 0→100% caught.
- [x] 4.3 `dq_check_freshness` — minutes since MAX(_fivetran_synced) vs SLA. Verified.
- [x] 4.4 `seed_baselines(table, connection_id)` — writes row_count + per-column null_rate + schema_fingerprint via load job (read-after-write reliable). Seeded account_holders + transactions. Also added `dq_check_schema_mismatch` (INFORMATION_SCHEMA vs baseline fingerprint) — the reliable schema-drift detector per 2.5 finding.
- [x] 4.5 Table-allowlist (`KNOWN_TABLES`) + column validation against INFORMATION_SCHEMA; unknown table/column raises. No free-form SQL reaches BQ.
- [ ] 4.6 Set BQ custom quota on the GCP project to cap demo cost (low priority — tiny dataset, credits ample)

## 5. Capability: `agent-loop` (Week 3, days 1-2)

- [x] 5.1 7-step orchestration — `dq_sentinel/loop.py` `run_loop()`. Deterministic app-code sequencing (ADK = Agent Builder code-first per D1); Gemini invoked only in step 4. SCAN/DETECT/INSPECT (read MCP + BQ) → DIAGNOSE (validated, ≤2 retry) → APPROVE (injected callback) → ACT (act.py) → VERIFY (verify.py). 26/26 mocked-orchestration checks pass (`scripts/test_loop.py`). Live read path + baseline gate verified against loan_products (`scripts/run_loop.py`).
- [x] 5.2 "baseline missing" precondition — `run_loop` checks `bq.get_baseline(table,'row_count')` for every target table before INSPECT; terminates `status=baseline_missing` with a clear message, no inspect/diagnose/act. Verified live (loan_products has no clean baseline yet).
- [x] 5.3 Manual trigger endpoint — `POST /api/runs {connection_id}` (dq_sentinel/web/api.py) starts a detached run; the SPA's "Run scan now" button + connection picker (`GET /api/connections`) call it. Live-verified.
- [x] 5.4 Incident report struct + emission — every `run_loop` exit returns the spec report (triggered_at, detected_issues, root_cause_hypothesis, remediation_proposed, approval_decision, action_taken, verification_result, before/after_metrics, time_to_resolution) with a `status` of resolved/unresolved/no-issue/baseline_missing/diagnosis_failed.

## 6. Capability: `diagnosis-and-remediation` (Week 3, days 3-4)

- [x] 6.1 `propose_remediation` tool (dq_sentinel/diagnose.py) — typed params (Literal enums for severity/action) ARE the diagnosis schema (design D3). Internal tool, no Fivetran side effect. Verified: Gemini 3.5 Flash diagnosed the live loan_products drift → action=resync_tables, targets=[loan_products], severity=HIGH, evidence citing real numbers.
- [x] 6.2 `validate_payload()` + up-to-2-retry loop — `loop.diagnose_validated()` runs DIAGNOSE up to 3 attempts (1 + 2 retries), feeding validation errors back via the new `diagnose(payload, feedback=...)` arg; all-invalid → `verification_result=diagnosis_failed`. Verified in test_loop.
- [x] 6.3 Approval-gate UI — `dq_sentinel/web/templates/index.html` renders the gate card (severity badge, root cause, evidence list, the exact `act.planned_call` MCP tool+args preview, approve / reject+reason / modify-targets). The gate is bridged to HTTP via an asyncio.Future (web/runs.py): run_loop runs as a detached task, its `approval` callback parks on a Future, `POST /api/runs/{id}/decision` resolves it. Architecture chosen by a 16-agent design workflow (Decoupled Job Model); hardened against a 23-agent adversarial review (0 blockers). Modify-targets bounded to the allowlist before any write. Proven: test_web_gate 15/15 + test_web_http 16/16 + live uvicorn smoke.
- [x] 6.4 Step 7 verification — `dq_sentinel/verify.py`: poll loop (30s/30min defaults, configurable), re-run originally-failed checks via `bq.rerun()`, before/after metrics. DEVIATION: spec names `get_connection_state` but `GET /v1/connections/{id}/state` returns HTTP 405 live — poll `get_connection_details` instead (`status.sync_state` + `succeeded_at`/`failed_at`). Completion = `succeeded_at` advances past the pre-ACT value.
- [x] 6.5 TTR breakdown — incident report `time_to_resolution` = {total, agent, sync_wait, *_seconds}; agent = total − sync_wait (verify reports `sync_wait_seconds` from the poll loop). Verified in test_loop.

> Live ACT-write + VERIFY-poll against real Fivetran is the one path NOT yet run end-to-end: firing a real resync would mutate the staged loan_products drift fixture (and a resync can't fix a header-rename anyway — needs sheet revert + clean re-seed). Deferred to demo staging (task 7.1).

## 7. End-to-End Demo Scenario (Week 3, day 5)

- [◐] 7.1 Full RESOLVED loop proven end-to-end on LIVE infra 2026-06-04 via the agent-resolvable **stale-data / freshness** scenario (no source mutation needed): loosen_signal (account_holders) freshness 4541min>180 → Gemini diagnosed stale-data → `resync_connection` → approved → real Fivetran resync → freshness re-check 4541→0 → `status=resolved` (TTR total 3m11s / agent 2m34s / sync_wait 37s). Key learning: only a full resync rewrites `_fivetran_synced`; a no-op sync of an unchanged Sheet does not. The PRD §8 scenario-1 schema-drift variant additionally needs a source-revert (rename the Sheet header back) to reach resolved — that's the manual pre-stage step for the recorded demo.
- [ ] 7.2 Wire the freshness-violation scenario (pause connector)
- [ ] 7.3 Wire the data-loss scenario (delete 50% of orders rows)
- [ ] 7.4 Confirm each scenario completes within the on-demand sync budget verified in task 1.6

## 8. Hosting + Submission (Week 4)

- [x] 8.1 Containerize + deploy to Cloud Run — DONE 2026-06-04. Hosted URL: https://dq-sentinel-sjsibsau7a-uc.a.run.app (service `dq-sentinel`, region us-central1, project agent-era, runtime SA dq-sentinel-runtime). `Dockerfile` (pre-baked fivetran-mcp), `deploy.sh` (3 load-bearing flags). VERIFIED on the deployed service: UI serves, live Fivetran scan works from the container (pre-baked MCP binary + Secret Manager creds), a run executes (→ baseline_missing), and the heartbeat advances between requests → `--no-cpu-throttling` confirmed (detached ACT/VERIFY + parked Future won't freeze). GOTCHA: Cloud Run's GFE intercepts a bare `/healthz` (returns a Google 404 before reaching the container) — health route moved to `/api/health`.
- [ ] 8.2 Smoke test the hosted URL with one demo scenario
- [ ] 8.3 Update `README.md`: actual hosted URL, screenshots, quickstart, license badge correct
- [ ] 8.4 Record 3-minute demo video (English, narrated). Pre-stage break before recording per design.md D7
- [ ] 8.5 Upload video to YouTube/Vimeo with English subtitles
- [ ] 8.6 Submit Devpost form: hosted URL, repo URL, video URL, track = Fivetran, text description covering features/tech/data sources/learnings
- [ ] 8.7 Verify GitHub repo License field is detected and visible in sidebar

## 9. Buffer / Stretch (Week 4 if P0 done)

- [ ] 9.1 Add duplicate-detection DQ check (P1)
- [ ] 9.2 Add DQ dashboard view to frontend (P1)
- [ ] 9.3 Add Markdown incident-report export (P1)
- [ ] 9.4 If Gemini 3 has shipped, swap `GEMINI_MODEL_ID` and re-run all 6 break scenarios
