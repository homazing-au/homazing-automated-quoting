"""Send a message to Manoj's Telegram chat."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")


def send_message(text: str) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    result = send_message("✅ Homazing bot is connected and ready.")
    print("Sent:", result["ok"])
