"""
Zoho CRM OAuth2 — authorization code flow + token refresh.
Token stored in .tmp/zoho_token.json and auto-refreshed on expiry.
"""

import os
import json
import time
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("ZOHO_REDIRECT_URI", "http://localhost:8000/callback")
TOKEN_FILE    = Path(".tmp/zoho_token.json")
SCOPES        = "ZohoCRM.modules.ALL,ZohoCRM.contacts.ALL,ZohoCRM.settings.ALL"

TOKEN_FILE.parent.mkdir(exist_ok=True)

_auth_code = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h2>Authorised! You can close this tab.</h2>")

    def log_message(self, *args):
        pass


def _run_server(httpd):
    httpd.handle_request()


def authorise():
    """Open browser for one-time OAuth consent and save token."""
    import webbrowser

    auth_url = (
        f"https://accounts.zoho.com.au/oauth/v2/auth"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&scope={urllib.parse.quote(SCOPES)}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    httpd = HTTPServer(("localhost", 8000), _CallbackHandler)
    t = threading.Thread(target=_run_server, args=(httpd,))
    t.start()

    print("Opening browser for Zoho authorisation...")
    webbrowser.open(auth_url)
    t.join(timeout=120)

    if not _auth_code:
        raise RuntimeError("No auth code received — did you complete the browser login?")

    _exchange_code(_auth_code)
    print("Zoho authorised and token saved.")


def _exchange_code(code: str):
    resp = requests.post(
        "https://accounts.zoho.com.au/oauth/v2/token",
        params={
            "grant_type":    "authorization_code",
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri":  REDIRECT_URI,
            "code":          code,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token exchange failed: {data}")
    data["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    TOKEN_FILE.write_text(json.dumps(data, indent=2))


def _refresh_token(refresh_token: str) -> dict:
    resp = requests.post(
        "https://accounts.zoho.com.au/oauth/v2/token",
        params={
            "grant_type":    "refresh_token",
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    saved = json.loads(TOKEN_FILE.read_text())
    saved["access_token"] = data["access_token"]
    saved["expires_at"]   = time.time() + data.get("expires_in", 3600) - 60
    TOKEN_FILE.write_text(json.dumps(saved, indent=2))
    return saved


def get_access_token() -> str:
    """Return a valid access token, refreshing if needed."""
    if not TOKEN_FILE.exists():
        raise RuntimeError("Not authorised. Run: python tools/zoho_auth.py")
    token = json.loads(TOKEN_FILE.read_text())
    if time.time() >= token.get("expires_at", 0):
        token = _refresh_token(token["refresh_token"])
    return token["access_token"]



if __name__ == "__main__":
    authorise()
