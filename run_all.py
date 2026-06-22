"""Start both the Telegram bot and the approval server together.
Run from project root: python run_all.py
Stop with Ctrl+C.
"""
import subprocess
import sys
import threading
import os

from dotenv import load_dotenv
from pathlib import Path

# Load shared keys from Homazing parent .env, then project-level .env (project wins on conflicts)
# Path: run_all.py → Homazing Automated Quoting → Homazing (contains shared .env)
_parent_env = Path(__file__).parent.parent / ".env"
if _parent_env.exists():
    load_dotenv(_parent_env)
load_dotenv()

port = int(os.getenv("APPROVAL_PORT", 5000))


def run_approval_server():
    from tools.approval_server import app
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def run_bot():
    from tools.telegram_webhook import main
    main()


if __name__ == "__main__":
    print(f"Starting approval server on http://localhost:{port}")
    server_thread = threading.Thread(target=run_approval_server, daemon=True)
    server_thread.start()

    print("Starting Telegram bot...")
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
