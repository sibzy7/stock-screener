"""
yfinance data-fetcher API — runs on Render (non-GCP IPs).
Calls Yahoo Finance REST API directly via curl_cffi Chrome impersonation.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from curl_cffi.requests import Session

PORT = int(os.environ.get("PORT", 8080))

# Persistent session — impersonates Chrome TLS fingerprint
_SESSION = Session(impersonate="chrome")

YF_CHART  = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YF_QUOTE  = "https://query1.finance.yahoo.com/v11/finance/quoteSummary/{ticker}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}


def fetch_ticker(ticker: str) -> dict:
    # ── Price history ─────────────────────────────────────────────────────────
    resp = _SESSION.get(
        YF_CHART.format(ticker=ticker),
        params={"range": "1y", "interval": "1d", "includePrePost": "false"},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    chart = resp.json()

    result_data = chart.get("chart", {}).get("result")
    if not result_data:
        error = chart.get("chart", {}).get("error", {})
        return {"error": f"no chart data: {error}"}

    closes = result_data[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
    closes = [c for c in closes if c is not None]

    if len(closes) < 200:
        return {"error": f"insufficient history: {len(closes)} rows"}

    # ── P/E ratio ─────────────────────────────────────────────────────────────
    pe = None
    try:
        q_resp = _SESSION.get(
            YF_QUOTE.format(ticker=ticker),
            params={"modules": "summaryDetail"},
            headers=HEADERS,
            timeout=15,
        )
        if q_resp.ok:
            sd = q_resp.json().get("quoteSummary", {}).get("result", [{}])[0].get("summaryDetail", {})
            raw_pe = sd.get("trailingPE", {})
            pe = raw_pe.get("raw") if isinstance(raw_pe, dict) else raw_pe
    except Exception:
        pass  # PE is optional — defaults to 999 in screener

    return {
        "ticker": ticker,
        "closes": closes,
        "pe": float(pe) if pe is not None else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        ticker = body.get("ticker", "").strip()

        if not ticker:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "ticker required"}).encode())
            return

        try:
            result = fetch_ticker(ticker)
            status = 200 if "error" not in result else 422
        except Exception as e:
            result = {"error": str(e)}
            status = 500

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


if __name__ == "__main__":
    print(f"yfinance fetcher listening on port {PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
