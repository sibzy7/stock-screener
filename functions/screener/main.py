import json
import logging
import os
from datetime import datetime, date

import functions_framework
import pandas as pd
import yfinance as yf
from curl_cffi.requests import Session
from google.cloud import firestore, pubsub_v1, secretmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WATCHLIST = {
    "KLSE": ["1155.KL", "5347.KL", "5183.KL", "1023.KL"],
    "US": ["AAPL", "MSFT", "GOOGL", "NVDA"],
}

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
PUBSUB_TOPIC = "stock-alerts"

# Yahoo Finance blocks GCP IP ranges. curl_cffi impersonates a Chrome TLS fingerprint
# to bypass Cloudflare, and we route through a proxy (YF_PROXY_URL env var) to escape
# Yahoo's GCP IP block. Set YF_PROXY_URL to a residential/non-cloud HTTP proxy.
_PROXY_URL = os.environ.get("YF_PROXY_URL")  # e.g. "http://user:pass@host:port"


def _make_session() -> Session:
    s = Session(impersonate="chrome")
    if _PROXY_URL:
        s.proxies = {"http": _PROXY_URL, "https": _PROXY_URL}
        logger.info(f"yfinance session using proxy: {_PROXY_URL.split('@')[-1]}")
    return s


_YF_SESSION = _make_session()


def get_secret(client: secretmanager.SecretManagerServiceClient, name: str) -> str:
    path = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return client.access_secret_version(request={"name": path}).payload.data.decode()


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
        tk = yf.Ticker(ticker, session=_YF_SESSION)
        hist = tk.history(period="1y")
        if hist.empty or len(hist) < 200:
            logger.warning(f"{ticker}: insufficient history ({len(hist)} rows)")
            return None

        closes = hist["Close"]
        price = float(closes.iloc[-1])

        rsi = compute_rsi(closes)
        rsi_signal = rsi < 45

        macd_cross = compute_macd_cross(closes)

        ma200 = float(closes.rolling(200).mean().iloc[-1])
        above_200ma = price > ma200

        info = tk.info or {}
        pe_raw = info.get("trailingPE")
        pe = float(pe_raw) if pe_raw is not None else 999.0
        pe_signal = pe < 20

        score = sum([rsi_signal, macd_cross, above_200ma, pe_signal])
        if score >= 3:
            signal = "BUY"
        elif score == 2:
            signal = "WATCH"
        else:
            signal = "HOLD"

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
        logger.error(f"{ticker}: error during analysis — {e}", exc_info=True)
        return None


@functions_framework.http
def screener(request):
    body = request.get_json(silent=True) or {}
    market_filter = body.get("market")  # "KLSE", "US", or None for all

    db = firestore.Client()
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
