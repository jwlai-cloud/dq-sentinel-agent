#!/usr/bin/env bash
# Deploy DQ Sentinel to Cloud Run. The three load-bearing flags are baked in so
# they cannot be forgotten (the design's #1 deploy footgun):
#   --no-cpu-throttling : without it the detached ACT/VERIFY task + the parked
#                         approval Future silently freeze the instant a request
#                         returns. Background CPU MUST stay allocated.
#   --min-instances 1   : keep one warm; an idle human at the gate must not
#                         scale the instance (and its in-memory Future) to zero.
#   --max-instances 1   : the approval-gate Future lives in process memory; a
#                         second instance would not see it. (Freeze-deploy the
#                         final revision before judging — a rolling deploy still
#                         briefly runs two revisions; the startup orphan-sweep
#                         surfaces any run stranded by that window.)
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-agent-era}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-dq-sentinel}"
ACCOUNT="${GCLOUD_ACCOUNT:-junwei.lai@gmail.com}"
RUNTIME_SA="dq-sentinel-runtime@${PROJECT}.iam.gserviceaccount.com"

echo "Deploying ${SERVICE} to Cloud Run (project=${PROJECT}, region=${REGION})..."

gcloud run deploy "${SERVICE}" \
  --source . \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --account "${ACCOUNT}" \
  --service-account "${RUNTIME_SA}" \
  --no-cpu-throttling \
  --min-instances 1 \
  --max-instances 1 \
  --timeout 600 \
  --concurrency 40 \
  --memory 1Gi \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global" \
  --set-secrets "FIVETRAN_API_KEY=FIVETRAN_API_KEY:latest,FIVETRAN_API_SECRET=FIVETRAN_API_SECRET:latest"

URL=$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" \
  --account "${ACCOUNT}" --format='value(status.url)')
echo
echo "Hosted URL: ${URL}"
echo "Smoke test (run against the DEPLOYED service, not local — CPU-throttle stalls only show on Cloud Run):"
echo "  curl -s ${URL}/api/health   # confirm beats advance between calls"
