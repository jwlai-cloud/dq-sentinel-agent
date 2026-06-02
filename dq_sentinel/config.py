"""Central configuration for DQ Sentinel.

All swappable knobs live here. The model ID is intentionally a single constant
(design.md D2) so it can be bumped in one place.

Secrets policy (spec `fivetran-integration`): the Fivetran credentials live in
Google Secret Manager and are injected into the process environment at startup
(locally via an export, on Cloud Run via a secret-backed env var). This module
reads them from the environment — it never reads a plaintext file.
"""
from __future__ import annotations

import os

# --- Model -----------------------------------------------------------------
# Gemini 3.5 Flash: GA 3-series flagship. Escalate to "gemini-3.1-pro-preview"
# only if diagnosis quality proves insufficient (design.md D2).
GEMINI_MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-3.5-flash")

# --- GCP / BigQuery --------------------------------------------------------
GCP_PROJECT = os.environ.get("GCP_PROJECT", "agent-era")
BQ_DATASET = os.environ.get("BQ_DATASET", "dq_sentinel")  # US multi-region (Fivetran-locked)

# Vertex model serving location. Gemini 3.x models are served from `global`,
# NOT a regional endpoint — us-central1 returns 403 "or it may not exist".
# google-genai reads this from GOOGLE_CLOUD_LOCATION; kept here for reference.
VERTEX_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

# --- Fivetran MCP ----------------------------------------------------------
FIVETRAN_MCP_COMMAND = "uvx"
FIVETRAN_MCP_ARGS = [
    "--from",
    "git+https://github.com/fivetran/fivetran-mcp",
    "fivetran-mcp",
]

# Read tools exposed to the model in agent loop steps 1-5 (pre-approval).
# Write tools are deliberately excluded here and only surfaced post-approval
# (design.md D4; spec `fivetran-integration`).
FIVETRAN_READ_TOOLS = [
    "list_connections",
    "get_connection_details",
    "get_connection_state",
    "get_connection_schema_config",
    "get_connection_column_config",
]

# Write tools, surfaced only on the post-approval execution path (step 6).
FIVETRAN_WRITE_TOOLS = [
    "sync_connection",
    "resync_connection",
    "resync_tables",
    "reload_connection_schema_config",
]


def fivetran_env(allow_writes: bool) -> dict[str, str]:
    """Build the env dict passed to the Fivetran MCP subprocess.

    `allow_writes` toggles the server-level write gate (FIVETRAN_ALLOW_WRITES).
    Steps 1-5 pass False; the step-6 execution path passes True.
    """
    key = os.environ.get("FIVETRAN_API_KEY")
    secret = os.environ.get("FIVETRAN_API_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "FIVETRAN_API_KEY / FIVETRAN_API_SECRET not in environment. "
            "Locally: export them from Secret Manager, e.g.\n"
            "  export FIVETRAN_API_KEY=$(gcloud secrets versions access latest "
            "--secret=FIVETRAN_API_KEY --project=agent-era)\n"
            "  export FIVETRAN_API_SECRET=$(gcloud secrets versions access latest "
            "--secret=FIVETRAN_API_SECRET --project=agent-era)"
        )
    return {
        "FIVETRAN_API_KEY": key,
        "FIVETRAN_API_SECRET": secret,
        "FIVETRAN_ALLOW_WRITES": "true" if allow_writes else "false",
    }
