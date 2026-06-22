"""
Exchanges the authorization code currently in QBO_REFRESH_TOKEN with Intuit
and writes the real refresh token back to .env.

Run this immediately after pasting the code from homazing.com.au/qbo-callback:
    python -m tools.qbo_exchange_code
"""
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
CODE          = os.getenv("QBO_REFRESH_TOKEN")   # user pasted the auth code here
REALM_ID      = os.getenv("QBO_REALM_ID")
REDIRECT_URI  = "https://homazing.com.au/qbo-callback"
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
ENV_PATH      = os.path.join(os.path.dirname(__file__), "..", ".env")

print(f"Exchanging code for tokens (realm: {REALM_ID}) ...")

resp = requests.post(
    TOKEN_URL,
    auth=(CLIENT_ID, CLIENT_SECRET),
    headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    data={"grant_type": "authorization_code", "code": CODE, "redirect_uri": REDIRECT_URI},
)

data = resp.json()

if "refresh_token" not in data:
    print(f"FAILED (HTTP {resp.status_code}):", data)
    raise SystemExit(1)

refresh_token = data["refresh_token"]

# Write real refresh token back to .env
with open(ENV_PATH, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

content = re.sub(r"^QBO_REFRESH_TOKEN=.*$", f"QBO_REFRESH_TOKEN={refresh_token}", content, flags=re.MULTILINE)

with open(ENV_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("\n✅ .env updated with real refresh token.")
print("\nNow paste this into Vercel (QBO_REFRESH_TOKEN):\n")
print(f"QBO_REFRESH_TOKEN={refresh_token}")
