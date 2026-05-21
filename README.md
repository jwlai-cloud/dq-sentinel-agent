# DQ Sentinel

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

An autonomous data-quality agent for financial-services data lakes. Watches Fivetran pipelines feeding daily regulatory reports, diagnoses root cause with Gemini, and proposes remediations through Fivetran's MCP server — with a human approval gate before any write. Built so the data engineer doesn't get paged at 3am for a sync miss that would silently break the morning compliance report.

Demo narrative: "Greedy Bank" — a fictional mid-tier Australian bank whose APRA reporting depends on overnight Fivetran syncs.

Built for the **[Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) — Fivetran track**. Deadline: 2026-06-11.

## Status

Pre-implementation. Architecture and capability specs are version-controlled under [`openspec/`](openspec/). The authoritative product spec is [`docs/PRD.md`](docs/PRD.md).

- Hosted URL: _coming week 4_
- Demo video: _coming week 4_

## What it does

1. **SCAN** every Fivetran connection via MCP.
2. **DETECT** sync failures, schema drift, sync delays.
3. **INSPECT** flagged tables with parameterized BigQuery checks (row count, null rate, freshness).
4. **DIAGNOSE** with Gemini, correlating pipeline metadata + DQ signals into a ranked root-cause hypothesis.
5. **RECOMMEND + APPROVE** — the human gate. The model proposes a tool call; you click approve.
6. **ACT** via Fivetran MCP write tools (`sync_connection`, `resync_tables`, `reload_schema`).
7. **VERIFY** — re-run failed checks, emit incident report with before/after metrics and TTR.

## Stack

- Orchestration: Google Cloud Agent Builder (Vertex AI)
- LLM: Gemini 2.5 Pro (pinned, swappable to Gemini 3 when available)
- Pipeline I/O: [fivetran/fivetran-mcp](https://github.com/fivetran/fivetran-mcp)
- Data warehouse: BigQuery (Python client wrapped as a custom Agent Builder tool)
- Demo source: Google Sheets → Fivetran → BigQuery
- Hosting: Cloud Run

## Repository layout

```
docs/PRD.md                  Product requirements (source of truth)
openspec/                    Versioned architecture + capability specs
  changes/                   Proposed and applied changes
  specs/                     Current capability specs (populated as changes apply)
demo-data/                   Seeded Greedy Bank demo data
  generate.py                uv-runnable faker script (PEP-723 inline deps)
  csv/                       Generated CSVs: 3 clean + 5 pre-broken variants
LICENSE                      Apache-2.0
```

## Demo data

Reproducible Greedy Bank dataset (3 sheets, ~2,600 rows, AUD).

```bash
uv run demo-data/generate.py
```

Produces 3 clean CSVs (`account_holders`, `transactions`, `loan_products`) plus 5 pre-broken variants matching the break scenarios in PRD §8 (null-injection, duplicates, data-loss, distribution-shift, schema-rename). Seeded — same output every run.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
