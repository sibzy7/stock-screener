"""
yfinance data-fetcher API — runs on Render (non-GCP IPs).
GCP screener calls this to get price history + PE, avoiding
Yahoo Finance's GCP IP block.
"""
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

import yfinance as yf
import pandas as pd

PORT = int(os.environ.get("PORT", 8080))


def fetch_ticker(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="1y", auto_adjust=True)

    if hist.empty or len(hist) < 200:
        return {"error": f"insufficient history: {len(hist)} rows"}

    closes = hist["Close"].tolist()
    info = tk.info or {}
    pe_raw = info.get("trailingPE")

    return {
        "ticker": ticker,
        "closes": closes,
        "pe": float(pe_raw) if pe_raw is not None else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # silence access logs

    def do_GET(self):
        """Health check"""
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
