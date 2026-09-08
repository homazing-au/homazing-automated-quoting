"""Single source of truth for getting a QuickBooks Online access token.

Intuit rotates the refresh token on EVERY use — the old one is invalidated
the instant a new one is issued. This module is the only place that should
ever call the refresh endpoint, so there is exactly one correct
read-refresh-persist implementation instead of ad-hoc copies that can drift
out of sync with each other (which is what caused repeated token corruption
in earlier sessions).

Mirrors homazing-website's lib/qbo.ts getQboAccessToken() exactly: Redis is
the source of truth (read first, write back on rotation), .env is only a
local fallback.
"""

import base64
import datetime
import os
import urllib.parse
import urllib.request

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


def _redis_get(key: str) -> str | None:
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/get/{urllib.parse.quote(key)}",
                                      headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            import json
            return json.loads(r.read()).get("result")
    except Exception:
        return None


def _redis_set(key: str, value: str) -> None:
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return
    # Path-based GET form only — a POST body with json.dumps(value) double-encodes
    # the string (wraps it in literal quote characters). This exact form is the
    # only one that has ever round-tripped correctly for this key.
    req = urllib.request.Request(f"{url.rstrip('/')}/set/{urllib.parse.quote(key)}/{urllib.parse.quote(value)}",
                                  headers={"Authorization": f"Bearer {token}"})
    urllib.request.urlopen(req, timeout=10)


def _update_env_file(key: str, value: str) -> None:
    import re
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}\n"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)


def get_qbo_access_token() -> str:
    """Refresh and return a QBO access token. Persists any rotated refresh
    token to Redis (source of truth) and the local .env (dev convenience) in
    the same call — never call the refresh endpoint any other way.
    """
    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")
    refresh_token = _redis_get("QBO_REFRESH_TOKEN") or os.getenv("QBO_REFRESH_TOKEN")
    if not refresh_token:
        raise RuntimeError("QBO_REFRESH_TOKEN not set in Redis or .env")

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        if data.get("error") == "invalid_grant":
            raise RuntimeError(
                "QBO_TOKEN_EXPIRED: refresh token is invalid. Run `python -m tools.qbo_oauth_setup` to re-authenticate."
            )
        raise RuntimeError(f"QBO auth failed: {data}")

    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        _update_env_file("QBO_REFRESH_TOKEN", new_refresh)
        _redis_set("QBO_REFRESH_TOKEN", new_refresh)
        _redis_set("QBO_TOKEN_ISSUED", datetime.date.today().isoformat())

    return access_token
