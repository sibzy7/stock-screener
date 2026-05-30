import json
import logging
import os
from datetime import datetime, date

import functions_framework
import pandas as pd
import requests
from google.cloud import firestore, pubsub_v1, secretmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WATCHLIST = {
    "KLSE": ["1155.KL", "5347.KL", "5183.KL", "1023.KL"],
    "US": ["AAPL", "MSFT", "GOOGL", "NVDA"],
}

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
PUBSUB_TOPIC = "stock-alerts"

# Render fetcher API — runs yfinance on non-GCP IPs, bypassing Yahoo Finance block
FETCHER_URL = os.environ.get("FETCHER_URL", "").rstrip("/")


def fetch_ticker_data(ticker: str) -> dict:
    """Call the Render fetcher API to get price history + PE."""
    if not FETCHER_URL:
        raise RuntimeError("FETCHER_URL env var not set")
    resp = requests.post(
        FETCHER_URL,
        json={"ticker": ticker},
        timeout=90,  # allow for Render free-tier cold start (up to ~50s)
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(data["error"])
    return data


def compute_rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def compute_macd_cross(closes: pd.Series) -> bool:
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    # Bullish crossover: yesterday macd <= signal, today macd > signal
    return bool(macd.iloc[-2] <= signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1])


def analyze_ticker(ticker: str, market: str) -> dict | None:
    try:
        raw = fetch_ticker_data(ticker)
        closes = pd.Series(raw["closes"])
        price = float(closes.iloc[-1])
        pe_raw = raw.get("pe")
        pe = float(pe_raw) if pe_raw is not None else 999.0

        rsi = compute_rsi(closes)
        rsi_signal = rsi < 45
        macd_cross = compute_macd_cross(closes)
        ma200 = float(closes.rolling(200).mean().iloc[-1])
        above_200ma = price > ma200
        pe_signal = pe < 20

        score = sum([rsi_signal, macd_cross, above_200ma, pe_signal])
        signal = "BUY" if score >= 3 else "WATCH" if score == 2 else "HOLD"

        result = {
            "ticker": ticker,
            "market": market,
            "price": round(price, 4),
            "rsi": round(rsi, 2),
            "macd_cross": macd_cross,
            "above_200ma": above_200ma,
            "pe": round(pe, 2),
            "score": score,
            "signal": signal,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        logger.info(f"{ticker}: price={price:.2f} rsi={rsi:.2f} score={score} signal={signal}")
        return result

    except Exception as e:
        logger.error(f"{ticker}: error — {e}", exc_info=True)
        return None


@functions_framework.http
def screener(request):
    body = request.get_json(silent=True) or {}
    market_filter = body.get("market")

    # Warm up Render fetcher (free tier sleeps after 15 min inactivity)
    if FETCHER_URL:
        try:
            requests.get(FETCHER_URL, timeout=60)
            logger.info("Render fetcher warmed up")
        except Exception as e:
            logger.warning(f"Fetcher warm-up ping failed: {e}")

    db = firestore.Client(database="stock-signals")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)
    today = date.today().isoformat()

    results = []
    for market, tickers in WATCHLIST.items():
        if market_filter and market != market_filter:
            continue
        for ticker in tickers:
            data = analyze_ticker(ticker, market)
            if data is None:
                continue

            doc_id = f"{ticker}_{today}"
            db.collection("signals").document(doc_id).set(data)
            logger.info(f"Firestore write: signals/{doc_id}")

            if data["signal"] == "BUY":
                msg = json.dumps(data).encode()
                future = publisher.publish(topic_path, msg)
                logger.info(f"Published to {PUBSUB_TOPIC}: {future.result()}")

            results.append(data)

    return (json.dumps({"processed": len(results), "results": results}), 200,
            {"Content-Type": "application/json"})
