"""
Telegram long-polling loop. Receives messages and routes them to the quote agent.
Run with: python tools/telegram_webhook.py
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
BASE      = f"https://api.telegram.org/bot{BOT_TOKEN}"


def get_updates(offset: int) -> list:
    resp = requests.get(f"{BASE}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=35)
    resp.raise_for_status()
    return resp.json().get("result", [])


def send(text: str, chat_id: str = CHAT_ID) -> int | None:
    resp = requests.post(f"{BASE}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    return resp.json().get("result", {}).get("message_id")


def send_typing(chat_id: str) -> None:
    requests.post(f"{BASE}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)


def is_authorised(chat_id: str) -> bool:
    return str(chat_id) == str(CHAT_ID)


def main():
    from tools.quote_agent import handle_message, _load_session, _save_session

    start_time = int(datetime.now(timezone.utc).timestamp())
    print("Bot polling started. Press Ctrl+C to stop.")
    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                if msg.get("date", 0) < start_time:
                    continue
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()
                if not text or not chat_id:
                    continue
                if not is_authorised(chat_id):
                    send("Unauthorised.", chat_id)
                    continue
                reply_to_id = msg.get("reply_to_message", {}).get("message_id")
                # Capture stage BEFORE processing so confirmation messages map back to it
                is_command = text.lower() in ("/new", "/start", "/reset")
                prev_stage = _load_session(chat_id).get("stage", "") if not is_command else ""
                send_typing(chat_id)
                reply = handle_message(chat_id, text, reply_to_id=reply_to_id)
                if reply:
                    msg_id = send(reply, chat_id)
                    # Tag this bot message with the stage it confirmed (not the next stage)
                    if msg_id and prev_stage:
                        sess = _load_session(chat_id)
                        sess.setdefault("msg_map", {})[str(msg_id)] = prev_stage
                        _save_session(chat_id, sess)
        except KeyboardInterrupt:
            print("Stopped.")
            sys.exit(0)
        except Exception as e:
            msg = str(e)
            if "409" in msg and "Conflict" in msg:
                print("ERROR: Another bot instance is already running. Exiting to avoid duplicate processing.")
                sys.exit(1)
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
