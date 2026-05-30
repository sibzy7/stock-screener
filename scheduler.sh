#!/usr/bin/env bash
set -euo pipefail

SCREENER_URL="${1:?Usage: ./scheduler.sh <screener-url>}"
PROJECT_ID=$(gcloud config get-value project)
REGION="asia-southeast1"
SA="${PROJECT_ID}@appspot.gserviceaccount.com"

echo "==> Creating Cloud Scheduler jobs (project: ${PROJECT_ID})"

# ── KLSE morning run (9:00 AM MYT, weekdays) ────────────────────────────────
gcloud scheduler jobs describe klse-morning \
  --location="${REGION}" --project="${PROJECT_ID}" 2>/dev/null \
  && gcloud scheduler jobs delete klse-morning \
       --location="${REGION}" --project="${PROJECT_ID}" --quiet

gcloud scheduler jobs create http klse-morning \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --schedule="0 9 * * 1-5" \
  --time-zone="Asia/Kuala_Lumpur" \
  --uri="${SCREENER_URL}" \
  --message-body='{"market":"KLSE"}' \
  --headers="Content-Type=application/json" \
  --oidc-service-account-email="${SA}" \
  --oidc-token-audience="${SCREENER_URL}"

echo "==> Created job: klse-morning"

# ── US market close run (10:30 PM MYT = 22:30, weekdays) ────────────────────
gcloud scheduler jobs describe us-close \
  --location="${REGION}" --project="${PROJECT_ID}" 2>/dev/null \
  && gcloud scheduler jobs delete us-close \
       --location="${REGION}" --project="${PROJECT_ID}" --quiet

gcloud scheduler jobs create http us-close \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --schedule="30 22 * * 1-5" \
  --time-zone="Asia/Kuala_Lumpur" \
  --uri="${SCREENER_URL}" \
  --message-body='{"market":"US"}' \
  --headers="Content-Type=application/json" \
  --oidc-service-account-email="${SA}" \
  --oidc-token-audience="${SCREENER_URL}"

echo "==> Created job: us-close"

echo ""
echo "  Scheduler jobs active. To trigger manually:"
echo "  gcloud scheduler jobs run klse-morning --location=${REGION}"
echo "  gcloud scheduler jobs run us-close     --location=${REGION}"
