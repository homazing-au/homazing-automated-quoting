"""
Quick test: verify QBO production credentials work.
Usage: python -m tools.test_qbo_auth
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("QBO_REFRESH_TOKEN")
REALM_ID      = os.getenv("QBO_REALM_ID")
ENVIRONMENT   = os.getenv("QBO_ENVIRONMENT", "sandbox")
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

print(f"Environment : {ENVIRONMENT}")
print(f"Realm ID    : {REALM_ID}")
print(f"Client ID   : {CLIENT_ID[:8]}..." if CLIENT_ID else "Client ID   : NOT SET")
print()

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, REALM_ID]):
    print("ERROR: One or more QBO env vars are missing.")
    raise SystemExit(1)

resp = requests.post(
    TOKEN_URL,
    auth=(CLIENT_ID, CLIENT_SECRET),
    headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    data={"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN},
)

print(f"Token refresh HTTP {resp.status_code}")
data = resp.json()

if "access_token" not in data:
    print("FAILED:", data)
    raise SystemExit(1)

print("Access token obtained successfully.")

# Try a simple query against the API
base = (
    "https://quickbooks.api.intuit.com"
    if ENVIRONMENT == "production"
    else "https://sandbox-quickbooks.api.intuit.com"
)
api_url = f"{base}/v3/company/{REALM_ID}/query"
headers = {"Authorization": f"Bearer {data['access_token']}", "Accept": "application/json"}

q_resp = requests.get(api_url, headers=headers, params={"query": "select * from CompanyInfo"})
print(f"CompanyInfo query HTTP {q_resp.status_code}")

if q_resp.ok:
    info = q_resp.json().get("QueryResponse", {}).get("CompanyInfo", [{}])[0]
    print(f"Company name: {info.get('CompanyName')}")
    print(f"Country     : {info.get('Country')}")
    print("\nSUCCESS - credentials are valid and QBO connection works.")
else:
    print("CompanyInfo query failed:", q_resp.text[:400])
