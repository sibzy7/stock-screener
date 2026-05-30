#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=$(gcloud config get-value project)
REGION="asia-southeast1"
SA="${PROJECT_ID}@appspot.gserviceaccount.com"

echo "==> Project: ${PROJECT_ID}  Region: ${REGION}"

# ── Enable required APIs first ───────────────────────────────────────────────
echo "==> Enabling required APIs (this may take a minute)..."
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  eventarc.googleapis.com \
  --project="${PROJECT_ID}"

# ── Grant Pub/Sub the token creator role (needed for Eventarc triggers) ──────
PUBSUB_SA="service-$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')@gcp-sa-pubsub.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PUBSUB_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --condition=None 2>/dev/null || true

# ── Pub/Sub topic ────────────────────────────────────────────────────────────
echo "==> Ensuring Pub/Sub topic 'stock-alerts' exists..."
gcloud pubsub topics describe stock-alerts --project="${PROJECT_ID}" 2>/dev/null \
  || gcloud pubsub topics create stock-alerts --project="${PROJECT_ID}"

# ── Firestore (native mode) ──────────────────────────────────────────────────
echo "==> Ensuring Firestore database exists..."
gcloud firestore databases describe --project="${PROJECT_ID}" 2>/dev/null \
  || gcloud firestore databases create \
       --project="${PROJECT_ID}" \
       --location="${REGION}" \
       --type=firestore-native

# ── Deploy screener ──────────────────────────────────────────────────────────
echo "==> Deploying screener function..."
gcloud functions deploy screener \
  --gen2 \
  --runtime=python311 \
  --region="${REGION}" \
  --source=functions/screener \
  --entry-point=screener \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512MB \
  --timeout=300s \
  --service-account="${SA}" \
  --project="${PROJECT_ID}"

SCREENER_URL=$(gcloud functions describe screener \
  --gen2 --region="${REGION}" --project="${PROJECT_ID}" \
  --format="value(serviceConfig.uri)")

echo "==> Screener URL: ${SCREENER_URL}"

# ── Deploy alerter ───────────────────────────────────────────────────────────
echo "==> Deploying alerter function..."
gcloud functions deploy alerter \
  --gen2 \
  --runtime=python311 \
  --region="${REGION}" \
  --source=functions/alerter \
  --entry-point=alerter \
  --trigger-topic=stock-alerts \
  --memory=256MB \
  --timeout=60s \
  --service-account="${SA}" \
  --project="${PROJECT_ID}"

ALERTER_URL=$(gcloud functions describe alerter \
  --gen2 --region="${REGION}" --project="${PROJECT_ID}" \
  --format="value(serviceConfig.uri)")

echo ""
echo "══════════════════════════════════════════════"
echo "  Deployed URLs"
echo "  Screener : ${SCREENER_URL}"
echo "  Alerter  : ${ALERTER_URL}"
echo "══════════════════════════════════════════════"
echo ""
echo "  Next: run ./scheduler.sh ${SCREENER_URL}"
