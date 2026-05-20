# PRD: DQ Sentinel — Data Quality Investigator Agent

**Author:** Junwei Lai
**Date:** 2026-05-19
**Hackathon:** Google Cloud Rapid Agent Hackathon (Fivetran Track)
**Deadline:** June 11, 2026
**Status:** Draft

---

## 1. Problem Statement

Data teams spend 30-40% of their time on data quality issues. When a Fivetran sync fails, a source schema drifts, or data anomalies creep in, the typical workflow is:

1. Someone notices a broken dashboard (hours to days after the issue)
2. Manual investigation: check Fivetran UI, query BigQuery, read logs
3. Root cause diagnosis: cross-reference pipeline metadata with actual data
4. Fix: re-sync, patch schema, backfill — all manual clicks

**Average time to detect + resolve: 4-8 hours.**

No existing tool combines pipeline health (Fivetran) with data inspection (BigQuery) into an autonomous agent that detects, diagnoses, and remediates in one loop.

---

## 2. Product Vision

**DQ Sentinel** is an AI agent that autonomously monitors Fivetran pipelines and BigQuery data quality — detecting brittle points, diagnosing root causes, and executing fixes with user approval.

**One-liner:** "An AI data quality engineer that watches your pipelines 24/7 and fixes problems before your stakeholders notice."

---

## 3. Target User

- **Primary:** Data engineers managing 10+ Fivetran connectors with BigQuery destination
- **Secondary:** Analytics engineers who own dbt models downstream of Fivetran syncs
- **Hackathon demo persona:** Solo data engineer at a mid-size company, overwhelmed by pipeline alerts

---

## 4. Hackathon Requirements Mapping

| Hackathon Requirement | How DQ Sentinel Meets It |
|---|---|
| Google Cloud Agent Builder | Agent orchestration layer |
| Gemini 3 | Reasoning engine for diagnosis + remediation planning |
| Fivetran MCP Server | Pipeline health, schema metadata, sync control |
| Solves real-world challenge | Data quality = universal pain point |
| Multi-step agent (not chatbot) | 7-step autonomous workflow: scan → detect → inspect → diagnose → recommend → act → verify |
| User control | Approval gate before any write operation |

---

## 5. Core Agent Workflow

```
                    ┌─────────────┐
                    │   TRIGGER   │
                    │ (scheduled  │
                    │  or manual) │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  1. SCAN    │  Fivetran MCP: list all connections
                    │             │  get_connection_details for each
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  2. DETECT  │  Flag: sync failures, schema changes,
                    │             │  sync delays, error states
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  3. INSPECT │  BigQuery: run DQ queries on flagged tables
                    │             │  - Row count vs baseline
                    │             │  - Null rate spikes
                    │             │  - Freshness (max timestamp)
                    │             │  - Duplicate detection
                    │             │  - Distribution anomalies
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ 4. DIAGNOSE │  Gemini 3: correlate pipeline metadata
                    │             │  + data signals → root cause hypothesis
                    └──────┬──────┘
                           │
                    ┌──────▼──────────┐
                    │ 5. RECOMMEND    │  Present findings + remediation options
                    │    (+ APPROVE)  │  User approves before any write action
                    └──────┬──────────┘
                           │
                    ┌──────▼──────┐
                    │   6. ACT    │  Fivetran MCP: resync_connection,
                    │             │  resync_tables, modify_connection_schema
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  7. VERIFY  │  Re-run DQ queries, confirm fix
                    │             │  Generate incident report
                    └─────────────┘
```

---

## 6. Feature Specification

### 6.1 Pipeline Health Scanner (Fivetran MCP)

**Tools used:** `list_connections`, `get_connection_details`, `get_connection_state`, `get_connection_schema_config`

**Detects:**
| Signal | How Detected | Severity |
|---|---|---|
| Sync failure | `connection.status.sync_state == "failed"` | CRITICAL |
| Sync delayed | `last_sync_completed` > 2x expected interval | HIGH |
| Schema change | `get_connection_schema_config` diff vs cached baseline | MEDIUM |
| Connection broken | `connection.status.setup_state != "connected"` | CRITICAL |
| Sync warning | `connection.status.sync_state == "warning"` | MEDIUM |

### 6.2 Data Quality Inspector (BigQuery)

**Runs parameterized SQL against synced tables in BQ.**

**DQ Checks:**

| Check | SQL Pattern | Threshold |
|---|---|---|
| **Row count anomaly** | `SELECT COUNT(*) FROM table` vs 7-day rolling avg | > 30% deviation |
| **Null rate spike** | `SELECT COUNTIF(col IS NULL) / COUNT(*) FROM table` per column | > 2x baseline |
| **Freshness violation** | `SELECT MAX(_fivetran_synced) FROM table` | > SLA window |
| **Duplicate detection** | `SELECT pk, COUNT(*) FROM table GROUP BY pk HAVING COUNT(*) > 1` | Any duplicates |
| **Value distribution shift** | `APPROX_QUANTILES(numeric_col, 100)` vs baseline | p50 shift > 20% |
| **Schema mismatch** | `INFORMATION_SCHEMA.COLUMNS` vs Fivetran schema config | Any diff |

**Baseline storage:** BQ table `dq_sentinel.baselines` stores rolling stats per table/column, updated each successful scan.

### 6.3 Diagnostic Engine (Gemini 3)

**Input to Gemini:** Structured JSON with:
- Fivetran connection metadata (status, last sync, schema config)
- DQ check results (which checks failed, by how much)
- Historical baseline data

**Gemini produces:**
- Root cause hypothesis (ranked by likelihood)
- Severity classification (CRITICAL / HIGH / MEDIUM / LOW)
- Affected downstream assets (if metadata available)
- Recommended remediation actions

**Example diagnosis:**
```json
{
  "root_cause": "Source schema change: column 'email' renamed to 'user_email' in source. Fivetran created new column, old column receiving NULLs for new rows.",
  "severity": "HIGH",
  "evidence": [
    "Fivetran schema shows new column 'user_email' added 2h ago",
    "Column 'email' null rate jumped from 2% to 41%",
    "Row count normal — no data loss, only misrouting"
  ],
  "remediation": [
    {"action": "resync_tables", "tables": ["customer_orders"], "reason": "Backfill with correct column mapping"},
    {"action": "manual", "description": "Update downstream dbt model to use 'user_email' column"}
  ]
}
```

### 6.4 Remediation Engine (Fivetran MCP + User Approval)

**Automated actions (with user approval):**
| Action | Fivetran MCP Tool | When |
|---|---|---|
| Re-sync connection | `sync_connection` | Sync failure, stale data |
| Re-sync specific tables | `resync_tables` | Table-level issues |
| Reload schema | `reload_connection_schema_config` | Schema drift detected |

**Manual recommendations (agent cannot automate):**
- dbt model changes
- Dashboard fixes
- Source system fixes
- Schema mapping changes in Fivetran UI

### 6.5 Verification Loop

After remediation executes:
1. Wait for sync completion (poll `get_connection_state`)
2. Re-run all failed DQ checks
3. Compare results to baseline
4. Generate incident report:
   - What was detected
   - Root cause
   - Action taken
   - Before/after metrics
   - Time to resolution

---

## 7. Architecture

```
┌──────────────────────────────────────────────────────┐
│                Google Cloud Agent Builder             │
│  ┌────────────────────────────────────────────────┐  │
│  │              Gemini 3 (Reasoning)              │  │
│  │  - Diagnosis                                    │  │
│  │  - Remediation planning                        │  │
│  │  - Natural language reporting                   │  │
│  └───────────┬────────────────────┬───────────────┘  │
│              │                    │                   │
│  ┌───────────▼──────┐  ┌────────▼────────────┐      │
│  │  Fivetran MCP    │  │  BigQuery Tool      │      │
│  │  Server (Tools)  │  │  (SQL execution)    │      │
│  │                  │  │                      │      │
│  │  - list_conn     │  │  - DQ check queries │      │
│  │  - get_details   │  │  - Baseline queries │      │
│  │  - get_schema    │  │  - INFORMATION_     │      │
│  │  - sync_conn     │  │    SCHEMA queries   │      │
│  │  - resync_tables │  │  - Incident log     │      │
│  └───────────┬──────┘  └────────┬────────────┘      │
│              │                    │                   │
└──────────────┼────────────────────┼───────────────────┘
               │                    │
       ┌───────▼──────┐    ┌───────▼───────┐
       │  Fivetran    │    │  BigQuery     │
       │  (SaaS)      │    │  (GCP)       │
       └──────────────┘    └───────────────┘

┌──────────────────────────────────────────────────────┐
│                    Frontend (Mesop/Streamlit)         │
│  - Agent conversation UI                              │
│  - DQ dashboard (table health overview)              │
│  - Incident history                                   │
│  - Approval workflow (approve/reject remediation)    │
└──────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Agent orchestration | Google Cloud Agent Builder (Vertex AI) | Hackathon requirement |
| LLM | Gemini 3 | Hackathon requirement |
| Pipeline metadata | Fivetran MCP Server (`fivetran/fivetran-mcp`) | Hackathon requirement (partner MCP) |
| Data warehouse | BigQuery | Fivetran destination, DQ inspection target |
| BQ access | BigQuery Python client or BQ MCP | Execute DQ queries |
| Frontend | Mesop (Google's Python UI) or Streamlit | Fast to build, Python-native |
| Hosting | Cloud Run | Hackathon requires hosted URL |
| Repo | GitHub (public, open-source) | Hackathon requirement |

---

## 8. Demo Data Setup

### Source: Google Sheets → Fivetran → BigQuery

**Why Google Sheets:**
- Free Fivetran connector
- Easy to corrupt data for demo (inject nulls, rename columns, delete rows)
- No infrastructure to manage
- Relatable to judges ("even a spreadsheet can break your pipeline")

**Demo tables (3 sheets):**

| Sheet/Table | Columns | Rows | Purpose |
|---|---|---|---|
| `customers` | id, name, email, signup_date, country | ~500 | Null rate, duplicate detection |
| `orders` | id, customer_id, amount, currency, order_date, status | ~2000 | Row count anomaly, distribution shift |
| `products` | id, name, category, price, is_active | ~100 | Schema change demo |

### Pre-scripted "Break" Scenarios for Demo

| Scenario | How to Break | What Agent Detects |
|---|---|---|
| **Schema drift** | Rename `email` → `user_email` in sheet | Schema mismatch + null spike on old column |
| **Data loss** | Delete 50% of rows in `orders` sheet | Row count anomaly (50% drop) |
| **Null injection** | Clear `amount` column for recent orders | Null rate spike on `amount` |
| **Duplicate injection** | Copy-paste 100 rows in `customers` | Duplicate PK detection |
| **Sync failure** | Revoke Fivetran's Google Sheets access | Connection broken, sync failure |
| **Freshness violation** | Pause Fivetran connector for 2+ hours | Freshness SLA exceeded |

---

## 9. Success Criteria (Judging Alignment)

| Judging Criterion | How We Score High |
|---|---|
| **Technological Implementation** | Deep Fivetran MCP integration (6+ tools), Gemini 3 multi-step reasoning, BQ DQ queries, Agent Builder orchestration |
| **Design** | Clean conversational UI, approval workflow, incident dashboard, DQ health overview |
| **Potential Impact** | Every data team has this problem. Quantifiable: "4h MTTR → 2min." Deployable at any Fivetran + BQ org. |
| **Quality of the Idea** | Novel combination: pipeline metadata (Fivetran) + data inspection (BQ) + AI diagnosis (Gemini) in one autonomous loop. No existing tool does this. |

---

## 10. MVP Scope (Must-Have for Hackathon)

### P0 — Ship or Fail

- [ ] Fivetran MCP integration: scan connections, get status, get schema
- [ ] BQ DQ checks: row count, null rate, freshness (3 checks minimum)
- [ ] Gemini 3 diagnosis: correlate pipeline + data signals → root cause
- [ ] Remediation: resync via Fivetran MCP with user approval
- [ ] Verification: re-run checks post-fix
- [ ] Demo: 1 end-to-end scenario (schema drift + null spike → detect → diagnose → fix → verify)
- [ ] Hosted on Cloud Run
- [ ] Public GitHub repo with LICENSE
- [ ] 3-minute demo video

### P1 — Nice to Have (If Time Permits)

- [ ] DQ baseline tracking (rolling averages in BQ)
- [ ] Multiple simultaneous issues detected
- [ ] Incident report generation (Markdown/PDF)
- [ ] DQ dashboard UI (table health heatmap)
- [ ] Duplicate detection check
- [ ] Distribution shift check

### P2 — Stretch Goals

- [ ] Webhook-triggered scanning (Fivetran → agent on sync complete)
- [ ] dbt model impact analysis
- [ ] Slack notification integration
- [ ] Historical incident timeline
- [ ] Cost estimation ("this resync will process ~X GB")

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Agent Builder learning curve too steep | HIGH | HIGH | Fallback: Python + Gemini API + ADK directly, skip Agent Builder |
| Fivetran MCP auth issues | MEDIUM | HIGH | Test in week 1; fallback to REST API wrapper |
| Gemini 3 not available yet | LOW | CRITICAL | Use Gemini 2.5 Pro; swap model ID when 3 launches |
| BQ DQ queries too slow for demo | LOW | MEDIUM | Pre-aggregate baselines; use small demo dataset |
| Google Sheets sync too slow | MEDIUM | LOW | Pre-sync data; only demo incremental changes |
| Scope creep | HIGH | HIGH | Strict P0 only until week 3; P1 only if P0 done and polished |

---

## 12. Timeline

| Week | Dates | Milestone | Deliverable |
|---|---|---|---|
| **1** | May 19-25 | Foundation | Fivetran account + Sheets→BQ pipeline working. Agent Builder or ADK "hello world" with Fivetran MCP. BQ DQ query library drafted. |
| **2** | May 26-Jun 1 | Core Loop | Scan→Detect→Inspect→Diagnose flow end-to-end. Gemini producing structured diagnosis from real data. |
| **3** | Jun 2-8 | Full Agent | Recommend→Act→Verify loop. User approval gate. Basic UI. All 3 demo scenarios working. |
| **4** | Jun 9-11 | Polish + Ship | Demo video recorded. Cloud Run deployed. README polished. Devpost submitted. |

**Hard deadline:** June 11, 2026 2:00pm PDT

---

## 13. Open Questions

1. **Agent Builder vs ADK?** — Need to evaluate Google Cloud Agent Builder maturity. If too rigid, use Google Agent Development Kit (ADK) with Gemini API directly. Decision by end of Week 1.
2. **Fivetran free tier limits?** — How many connectors? Sync frequency limits? Need to verify.
3. **BQ access from agent** — Use BigQuery MCP server, or BQ Python client as custom tool in Agent Builder? Test both.
4. **Gemini 3 availability** — Is Gemini 3 released by hackathon date? If not, use Gemini 2.5 Pro.
5. **Team?** — Solo or finding teammates? Hackathon allows teams.

---

## Appendix A: Fivetran MCP Tools Used

| Tool | Read/Write | Purpose in DQ Sentinel |
|---|---|---|
| `list_connections` | Read | Discover all pipelines to monitor |
| `get_connection_details` | Read | Sync status, last sync time, error messages |
| `get_connection_state` | Read | Detailed sync state per table |
| `get_connection_schema_config` | Read | Schema metadata for drift detection |
| `get_connection_column_config` | Read | Column-level metadata |
| `reload_connection_schema_config` | Write | Refresh schema after source change |
| `sync_connection` | Write | Trigger re-sync for remediation |
| `resync_connection` | Write | Full historical re-sync |
| `resync_tables` | Write | Targeted table re-sync |

## Appendix B: BQ DQ Query Templates

### Row Count Check
```sql
SELECT
  COUNT(*) as current_count,
  (SELECT row_count FROM dq_sentinel.baselines 
   WHERE table_name = @table AND metric = 'row_count'
   ORDER BY checked_at DESC LIMIT 1) as baseline_count
FROM `{project}.{dataset}.{table}`
```

### Null Rate Check
```sql
SELECT
  '{column}' as column_name,
  COUNTIF({column} IS NULL) as null_count,
  COUNT(*) as total_count,
  ROUND(COUNTIF({column} IS NULL) / COUNT(*) * 100, 2) as null_pct
FROM `{project}.{dataset}.{table}`
```

### Freshness Check
```sql
SELECT
  MAX(_fivetran_synced) as last_synced,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(_fivetran_synced), MINUTE) as minutes_stale
FROM `{project}.{dataset}.{table}`
```

### Duplicate Check
```sql
SELECT
  {pk_column},
  COUNT(*) as occurrence_count
FROM `{project}.{dataset}.{table}`
GROUP BY {pk_column}
HAVING COUNT(*) > 1
LIMIT 10
```
