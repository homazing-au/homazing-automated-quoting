"""One-time OAuth2 authorization flow for QuickBooks Online.

Run this script directly (not via the bot). It opens a browser window for you
to log in to QuickBooks and authorize the app, then writes QBO_REFRESH_TOKEN
and QBO_REALM_ID into .env automatically.

Usage:
    python -m tools.qbo_oauth_setup
"""

import os
import re
import webbrowser
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
ENVIRONMENT   = os.getenv("QBO_ENVIRONMENT", "sandbox")
REDIRECT_URI  = "https://homazing.com.au/qbo-callback"
SCOPE         = "com.intuit.quickbooks.accounting"
AUTH_URL      = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
ENV_PATH      = os.path.join(os.path.dirname(__file__), "..", ".env")


def update_env_var(key: str, value: str):
    with open(ENV_PATH, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}\n"

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: QBO_CLIENT_ID / QBO_CLIENT_SECRET not set in .env")
        return

    auth_params = {
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPE,
        "state":         "homazing_qbo_setup",
    }
    auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"

    print("Opening browser for QuickBooks authorization...")
    print(f"If it doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("\nAfter authorizing in the browser, homazing.com.au/qbo-callback will show the CODE and REALM ID.")
    print("Paste them here:\n")
    code     = input("CODE: ").strip()
    realm_id = input("REALM ID: ").strip()
    if not code or not realm_id:
        print("ERROR: Code or Realm ID was empty.")
        return

    print(f"Received authorization code and Realm ID: {realm_id}")

    # Exchange code for tokens
    token_resp = requests.post(
        TOKEN_URL,
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    if not token_resp.ok:
        print(f"ERROR exchanging code for tokens: {token_resp.status_code} {token_resp.text}")
        return

    tokens = token_resp.json()
    refresh_token = tokens["refresh_token"]

    # Write tokens to .env automatically
    update_env_var("QBO_REFRESH_TOKEN", refresh_token)
    update_env_var("QBO_REALM_ID", realm_id)
    print("\n✅ .env updated.")

    # Push to Vercel via API (no CLI org ID issues)
    print("\nPushing tokens to Vercel...")
    import json, urllib.request, urllib.error, subprocess
    vercel_token = os.getenv("VERCEL_TOKEN")
    project_id   = os.getenv("VERCEL_PROJECT_ID")
    team_id      = os.getenv("VERCEL_TEAM_ID")

    if vercel_token and project_id and team_id:
        api_headers = {"Authorization": f"Bearer {vercel_token}", "Content-Type": "application/json"}
        req = urllib.request.Request(
            f"https://api.vercel.com/v9/projects/{project_id}/env?teamId={team_id}",
            headers={"Authorization": f"Bearer {vercel_token}"}
        )
        with urllib.request.urlopen(req) as r:
            existing = {e["key"]: e["id"] for e in json.loads(r.read()).get("envs", [])}

        for key, val in [("QBO_REFRESH_TOKEN", refresh_token), ("QBO_REALM_ID", realm_id)]:
            try:
                if key in existing:
                    body = json.dumps({"value": val, "target": ["production"]}).encode()
                    req2 = urllib.request.Request(
                        f"https://api.vercel.com/v9/projects/{project_id}/env/{existing[key]}?teamId={team_id}",
                        data=body, headers=api_headers, method="PATCH"
                    )
                else:
                    body = json.dumps({"key": key, "value": val, "target": ["production"], "type": "encrypted"}).encode()
                    req2 = urllib.request.Request(
                        f"https://api.vercel.com/v10/projects/{project_id}/env?teamId={team_id}",
                        data=body, headers=api_headers, method="POST"
                    )
                urllib.request.urlopen(req2)
                print(f"  ✅ {key} updated in Vercel")
            except urllib.error.HTTPError as e:
                print(f"  ❌ {key} Vercel update failed: {e.read()[:200]}")
                print(f"     Paste manually: {key}={val}")
    else:
        print("  ❌ VERCEL_TOKEN/PROJECT_ID/TEAM_ID not set — paste manually:")
        print(f"     QBO_REFRESH_TOKEN={refresh_token}")
        print(f"     QBO_REALM_ID={realm_id}")

    # Seed fresh token into Upstash Redis (so Vercel picks it up without a redeploy)
    print("\nSeeding token into Upstash Redis...")
    redis_url   = os.getenv("UPSTASH_REDIS_REST_URL", "")
    redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    if redis_url and redis_token:
        import json as _json
        today_str = __import__("datetime").date.today().isoformat()
        for rkey, rval in [("QBO_REFRESH_TOKEN", refresh_token), ("QBO_TOKEN_ISSUED", today_str)]:
            seed_req = urllib.request.Request(
                f"{redis_url.rstrip('/')}/set/{rkey}",
                data=_json.dumps(rval).encode(),
                headers={"Authorization": f"Bearer {redis_token}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(seed_req) as r:
                    result = _json.loads(r.read())
                    if result.get("result") == "OK":
                        print(f"  ✅ {rkey} seeded into Redis")
                    else:
                        print(f"  WARNING: {rkey} seed response: {result}")
            except urllib.error.HTTPError as e:
                print(f"  ❌ Redis seed failed for {rkey}: {e.read()[:200]}")
    else:
        print("  UPSTASH_REDIS_REST_URL/TOKEN not set — skipping Redis seed")

    print("\nNote: this refresh token is valid for 100 days. If it expires, re-run this script.")


if __name__ == "__main__":
    main()
