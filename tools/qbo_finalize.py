"""
Exchange an Intuit authorization code for a refresh token and write to .env.
Usage: python -m tools.qbo_finalize <code> <realm_id>
"""
import os
import re
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
REDIRECT_URI  = "https://homazing.com.au/qbo-callback"
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
ENV_PATH      = os.path.join(os.path.dirname(__file__), "..", ".env")

if len(sys.argv) != 3:
    print("Usage: python -m tools.qbo_finalize <code> <realm_id>")
    sys.exit(1)

code     = sys.argv[1].strip()
realm_id = sys.argv[2].strip()

print(f"Exchanging code for tokens (realm: {realm_id}) ...")

resp = requests.post(
    TOKEN_URL,
    auth=(CLIENT_ID, CLIENT_SECRET),
    headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
)

data = resp.json()

if "refresh_token" not in data:
    print(f"FAILED (HTTP {resp.status_code}):", data)
    sys.exit(1)

refresh_token = data["refresh_token"]

# Write to .env
with open(ENV_PATH, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

for key, val in [("QBO_REFRESH_TOKEN", refresh_token), ("QBO_REALM_ID", realm_id)]:
    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{key}={val}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={val}\n"

with open(ENV_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("✅ .env updated.")
print(f"\nPaste this into Vercel (QBO_REFRESH_TOKEN):\n\n{refresh_token}")
