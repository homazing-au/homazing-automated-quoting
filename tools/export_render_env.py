"""Write a Render-ready .env file from the local .env (only the vars Render needs)."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load parent .env first (has ANTHROPIC_API_KEY), then project .env
parent_env = Path(__file__).parent.parent.parent / ".env"
if parent_env.exists():
    load_dotenv(parent_env)
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

RENDER_VARS = [
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "MAILERSEND_API_KEY",
    "FROM_EMAIL",
]

out_path = Path(__file__).parent.parent / ".env.render"
lines = []
missing = []

for key in RENDER_VARS:
    val = os.getenv(key, "")
    if val:
        lines.append(f"{key}={val}")
    else:
        missing.append(key)

out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Written to: {out_path}")
if missing:
    print(f"WARNING — missing values (add manually): {', '.join(missing)}")
else:
    print(f"All {len(lines)} variables exported.")
