import base64
import json
import logging
import os

import functions_framework
import requests
from google.cloud import secretmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
_secret_cache: dict[str, str] = {}


def get_secret(name: str) -> str:
    if name in _secret_cache:
        return _secret_cache[name]
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    value = client.access_secret_version(request={"name": path}).payload.data.decode()
    _secret_cache[name] = value
    return value


def format_message(data: dict) -> str:
    market = data.get("market", "")
    currency = "RM" if market == "KLSE" else "$"
    price = data.get("price", 0)
    pe = data.get("pe", 999)
    pe_display = f"{pe:.2f}" if pe < 999 else "N/A"

    return (
        f"BUY SIGNAL: {data['ticker']} ({market})\n"
        f"Price: {currency}{price:.2f}\n"
        f"Score: {data['score']}/4\n"
        f"RSI: {data['rsi']} | MACD cross: {data['macd_cross']} | "
        f"Above 200MA: {data['above_200ma']} | P/E: {pe_display}\n"
        f"Checked: {data['timestamp']}"
    )


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    resp.raise_for_status()
    logger.info(f"Telegram message sent: {resp.json().get('ok')}")


@functions_framework.cloud_event
def alerter(cloud_event):
    try:
        raw = base64.b64decode(cloud_event.data["message"]["data"]).decode()
        data = json.loads(raw)
        logger.info(f"Received alert for {data.get('ticker')}")

        token = get_secret("telegram-token")
        chat_id = get_secret("telegram-chat-id")

        text = format_message(data)
        send_telegram(token, chat_id, text)

    except Exception as e:
        logger.error(f"Alerter error: {e}", exc_info=True)
        raise
