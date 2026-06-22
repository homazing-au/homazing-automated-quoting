"""
Create an Upstash Redis database, seed QBO_REFRESH_TOKEN into it,
and push the connection details to Vercel env vars.

Usage:
    python -m tools.setup_vercel_kv
"""

import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(ENV_PATH, override=True)

UPSTASH_EMAIL     = os.getenv("UPSTASH_EMAIL", "")
UPSTASH_API_KEY   = os.getenv("UPSTASH_API_KEY", "")
QBO_REFRESH_TOKEN = os.getenv("QBO_REFRESH_TOKEN", "")
VERCEL_TOKEN      = os.getenv("VERCEL_TOKEN", "")
PROJECT_ID        = os.getenv("VERCEL_PROJECT_ID", "")
TEAM_ID           = os.getenv("VERCEL_TEAM_ID", "")


def upstash(method, path, body=None):
    creds = base64.b64encode(f"{UPSTASH_EMAIL}:{UPSTASH_API_KEY}".encode()).decode()
    data  = json.dumps(body).encode() if body else None
    req   = urllib.request.Request(
        f"https://api.upstash.com{path}",
        data=data,
        headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        return (json.loads(text) if text.startswith("{") else {"error": text}), e.code


def vercel_api(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        f"https://api.vercel.com{path}",
        data=data,
        headers={"Authorization": f"Bearer {VERCEL_TOKEN}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        return (json.loads(text) if text.startswith("{") else {"error": text}), e.code


def update_env_var(key, val, existing):
    if key in existing:
        body = {"value": val, "target": ["production"]}
        vercel_api("PATCH", f"/v9/projects/{PROJECT_ID}/env/{existing[key]}?teamId={TEAM_ID}", body)
    else:
        body = {"key": key, "value": val, "target": ["production"], "type": "encrypted"}
        vercel_api("POST", f"/v10/projects/{PROJECT_ID}/env?teamId={TEAM_ID}", body)
    print(f"  ✅ {key} set in Vercel")


def main():
    if not UPSTASH_EMAIL or not UPSTASH_API_KEY:
        print("ERROR: UPSTASH_EMAIL / UPSTASH_API_KEY not set in .env")
        return
    if not QBO_REFRESH_TOKEN:
        print("ERROR: QBO_REFRESH_TOKEN not set in .env")
        return
    if not VERCEL_TOKEN or not PROJECT_ID or not TEAM_ID:
        print("ERROR: VERCEL_TOKEN / VERCEL_PROJECT_ID / VERCEL_TEAM_ID not set in .env")
        return

    # Step 1: Create Upstash Redis database (free tier, Sydney region)
    print("Creating Upstash Redis database...")
    db_data, status = upstash("POST", "/v2/redis/database", {
        "database_name": "homazing-qbo",
        "region":        "ap-southeast-2",  # Sydney — closest to Melbourne
        "tls":           True,
    })

    if status not in (200, 201):
        # Try global endpoint
        db_data, status = upstash("POST", "/v2/redis/database", {
            "database_name":  "homazing-qbo",
            "platform":       "aws",
            "primary_region": "ap-southeast-2",
            "tls":            True,
        })

    if status not in (200, 201):
        # Database may already exist from a previous run — list and find it
        print(f"  Create returned {status}, checking if database already exists...")
        list_data, _ = upstash("GET", "/v2/redis/databases")
        databases = list_data if isinstance(list_data, list) else list_data.get("databases", [])
        db_data = next((d for d in databases if d.get("database_name") == "homazing-qbo"), None)
        if not db_data:
            print(f"  ERROR: could not create or find database. Last error: {list_data}")
            return
        print("  Found existing database.")

    rest_url   = db_data.get("endpoint", "")
    rest_token = db_data.get("password", "")
    db_id      = db_data.get("database_id", db_data.get("id", ""))

    if not rest_url or not rest_token:
        print(f"  Unexpected response shape: {list(db_data.keys())}")
        print(f"  Full response: {json.dumps(db_data)[:500]}")
        return

    rest_url = f"https://{rest_url}" if not rest_url.startswith("http") else rest_url
    print(f"  ✅ Database created (ID: {db_id})")

    # Step 2: Seed QBO_REFRESH_TOKEN
    print("\nSeeding QBO_REFRESH_TOKEN into Redis...")
    seed_req = urllib.request.Request(
        f"{rest_url}/set/QBO_REFRESH_TOKEN",
        data=json.dumps(QBO_REFRESH_TOKEN).encode(),
        headers={"Authorization": f"Bearer {rest_token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(seed_req) as r:
            result = json.loads(r.read())
            if result.get("result") == "OK":
                print("  ✅ QBO_REFRESH_TOKEN seeded")
            else:
                print(f"  WARNING: unexpected seed response: {result}")
    except urllib.error.HTTPError as e:
        print(f"  ERROR seeding: {e.read()[:200]}")
        return

    # Step 3: Push connection details to Vercel
    print("\nPushing Redis credentials to Vercel...")
    env_data, _ = vercel_api("GET", f"/v9/projects/{PROJECT_ID}/env?teamId={TEAM_ID}")
    existing    = {e["key"]: e["id"] for e in env_data.get("envs", [])}

    update_env_var("UPSTASH_REDIS_REST_URL",   rest_url,   existing)
    update_env_var("UPSTASH_REDIS_REST_TOKEN",  rest_token, existing)

    # Step 4: Save to local .env
    print("\nUpdating local .env...")
    with open(ENV_PATH, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    import re
    for key, val in [("UPSTASH_REDIS_REST_URL", rest_url), ("UPSTASH_REDIS_REST_TOKEN", rest_token)]:
        pattern = rf"^{key}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, f"{key}={val}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={val}\n"

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print("  ✅ Local .env updated")

    print("\n✅ Upstash Redis ready. Next: update qbo.ts to use Redis for token storage.")


if __name__ == "__main__":
    main()
