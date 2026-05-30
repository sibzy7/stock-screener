# Stock Monitor — GCP Buy Signal System

Serverless stock screener running on Cloud Functions (gen2), Firestore, Pub/Sub, and Cloud Scheduler. Sends Telegram alerts for BUY signals.

## Architecture

```
Cloud Scheduler ──► screener (HTTP function)
                        │  writes every ticker → Firestore (signals/{ticker}_{date})
                        │  BUY signals only → Pub/Sub (stock-alerts)
                                                    │
                                             alerter (Pub/Sub function)
                                                    │
                                             Telegram message
```

## Watchlist

| Market | Tickers |
|--------|---------|
| KLSE   | 1155.KL (Maybank), 5347.KL (Tenaga), 5183.KL (PChem), 1023.KL (CIMB) |
| US     | AAPL, MSFT, GOOGL, NVDA |

## Signals

| Signal | Condition |
|--------|-----------|
| RSI    | RSI(14) < 45 |
| MACD   | MACD line crosses above signal line today |
| 200MA  | Price above 200-day moving average |
| P/E    | Trailing P/E < 20 |

Score 0–4 → **BUY** (≥3) / **WATCH** (2) / **HOLD** (<2)

## Setup

### 1. Deploy functions and infrastructure

```bash
chmod +x deploy.sh scheduler.sh
./deploy.sh
```

### 2. Set Telegram secrets

```bash
echo -n "YOUR_BOT_TOKEN" | gcloud secrets create telegram-token --data-file=-
echo -n "YOUR_CHAT_ID"   | gcloud secrets create telegram-chat-id --data-file=-
```

To update existing secrets:
```bash
echo -n "NEW_VALUE" | gcloud secrets versions add telegram-token --data-file=-
```

### 3. Set up schedulers

```bash
./scheduler.sh <screener-url>
```

### 4. Test manually

```bash
# Trigger screener for KLSE
curl -X POST <screener-url> \
  -H "Content-Type: application/json" \
  -d '{"market":"KLSE"}'

# Trigger screener for US
curl -X POST <screener-url> \
  -H "Content-Type: application/json" \
  -d '{"market":"US"}'
```

### 5. Check Firestore

```bash
gcloud firestore documents list --collection=signals
```

## Schedule (Asia/Kuala_Lumpur)

| Job | Cron | When |
|-----|------|------|
| klse-morning | `0 9 * * 1-5` | 9:00 AM weekdays (KLSE open) |
| us-close | `30 22 * * 1-5` | 10:30 PM weekdays (~30 min after NYSE close) |

## IAM requirements

The default App Engine service account needs:
- `roles/datastore.user` (Firestore)
- `roles/pubsub.publisher`
- `roles/secretmanager.secretAccessor`
