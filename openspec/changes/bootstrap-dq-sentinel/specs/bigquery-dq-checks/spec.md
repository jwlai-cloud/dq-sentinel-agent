## ADDED Requirements

### Requirement: P0 DQ check coverage

The system SHALL implement at minimum the following three parameterized DQ checks against tables in the Fivetran-landed BigQuery dataset: row-count anomaly, null-rate spike, and freshness violation. Each check SHALL return a structured result containing `check_name`, `table`, `column` (when applicable), `current_value`, `baseline_value`, `deviation`, `passed` (bool), `severity`.

#### Scenario: Row count anomaly
- **WHEN** a table's current row count deviates from its baseline by more than 30%
- **THEN** the row-count check returns `passed: false` with `deviation` = the absolute percentage delta

#### Scenario: Null rate spike
- **WHEN** a column's current null rate is more than 2× its baseline null rate
- **THEN** the null-rate check returns `passed: false` for that column with `current_value` and `baseline_value` populated

#### Scenario: Freshness violation
- **WHEN** the maximum `_fivetran_synced` timestamp on a table is older than the configured SLA window
- **THEN** the freshness check returns `passed: false` with `current_value` = minutes stale

### Requirement: BQ access is via a parameterized custom tool, not free-form SQL

The Gemini model SHALL NOT receive a tool that accepts arbitrary SQL strings. The model SHALL only call DQ check tools whose parameters are bound types (table name from a known list, column name validated against `INFORMATION_SCHEMA`, threshold from baseline). All SQL is templated in application code from the PRD Appendix B patterns.

#### Scenario: Injection attempt blocked
- **WHEN** the model attempts to pass `table="customers; DROP TABLE products"` to a DQ check tool
- **THEN** the tool rejects the call because the table name does not match the allowlist of known Fivetran-landed tables for this connection

### Requirement: Baseline storage contract

DQ baselines SHALL be stored in a single BigQuery table `dq_sentinel.baselines` with at minimum the columns: `connection_id` (string), `table_name` (string), `column_name` (string, nullable), `metric` (string, e.g. `row_count`, `null_rate`, `schema_fingerprint`), `metric_value` (string, JSON-encoded for non-scalar metrics), `metric_version` (int), `captured_at` (timestamp).

#### Scenario: Read latest baseline
- **WHEN** the inspect step requests the baseline `null_rate` for column `email` on table `customers`
- **THEN** the system queries `dq_sentinel.baselines` filtered by connection_id, table_name, column_name, metric, ordered by captured_at DESC, and returns the most recent row

#### Scenario: Append baseline on seed
- **WHEN** `seed_baselines(connection_id)` runs successfully
- **THEN** new rows are inserted (not updated) into `dq_sentinel.baselines` so historical baseline values are preserved

### Requirement: Inspect step runs only on flagged tables

The INSPECT step SHALL run DQ checks only against tables flagged by the DETECT step (schema change, sync delay, sync failure, sync warning). Tables with healthy Fivetran metadata SHALL NOT be inspected in a given run.

#### Scenario: Flagged subset
- **WHEN** detect flags 2 of 5 tables in a connection
- **THEN** inspect runs DQ checks against exactly those 2 tables, and the other 3 tables produce no BQ query cost in this run
