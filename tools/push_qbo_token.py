"""
Push the current local QBO_REFRESH_TOKEN from .env to Vercel and trigger a redeploy.
Run this whenever the local token has drifted ahead of Vercel (e.g. after any local QBO test).

Usage:
    python -m tools.push_qbo_token
"""

import json
import os
import subprocess
import urllib.error
import urllib.request

from dotenv import load_dotenv

ENV_PATH    = os.path.join(os.path.dirname(__file__), "..", ".env")
WEBSITE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "homazing-website"))

load_dotenv(ENV_PATH, override=True)

def main():
    refresh_token = os.getenv("QBO_REFRESH_TOKEN", "")
    realm_id      = os.getenv("QBO_REALM_ID", "")
    vercel_token  = os.getenv("VERCEL_TOKEN", "")
    project_id    = os.getenv("VERCEL_PROJECT_ID", "")
    team_id       = os.getenv("VERCEL_TEAM_ID", "")

    if not refresh_token:
        print("ERROR: QBO_REFRESH_TOKEN is empty in .env")
        return
    if not vercel_token or not project_id or not team_id:
        print("ERROR: VERCEL_TOKEN / VERCEL_PROJECT_ID / VERCEL_TEAM_ID not set in .env")
        return

    api_headers = {
        "Authorization": f"Bearer {vercel_token}",
        "Content-Type":  "application/json",
    }

    # Fetch existing env var IDs
    req = urllib.request.Request(
        f"https://api.vercel.com/v9/projects/{project_id}/env?teamId={team_id}",
        headers={"Authorization": f"Bearer {vercel_token}"},
    )
    with urllib.request.urlopen(req) as r:
        existing = {e["key"]: e["id"] for e in json.loads(r.read()).get("envs", [])}

    to_push = [("QBO_REFRESH_TOKEN", refresh_token)]
    if realm_id:
        to_push.append(("QBO_REALM_ID", realm_id))

    for key, val in to_push:
        try:
            if key in existing:
                body = json.dumps({"value": val, "target": ["production"]}).encode()
                req2 = urllib.request.Request(
                    f"https://api.vercel.com/v9/projects/{project_id}/env/{existing[key]}?teamId={team_id}",
                    data=body, headers=api_headers, method="PATCH",
                )
            else:
                body = json.dumps({"key": key, "value": val, "target": ["production"], "type": "encrypted"}).encode()
                req2 = urllib.request.Request(
                    f"https://api.vercel.com/v10/projects/{project_id}/env?teamId={team_id}",
                    data=body, headers=api_headers, method="POST",
                )
            urllib.request.urlopen(req2)
            print(f"  ✅ {key} pushed to Vercel")
        except urllib.error.HTTPError as e:
            print(f"  ❌ {key} failed: {e.read()[:300]}")
            return

    # Trigger redeploy
    print("\nTriggering Vercel redeploy...")
    r1 = subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "chore: sync QBO token to Vercel"],
        cwd=WEBSITE_DIR, capture_output=True, text=True,
    )
    r2 = subprocess.run(
        ["git", "push"],
        cwd=WEBSITE_DIR, capture_output=True, text=True,
    )
    if r2.returncode == 0:
        print("  ✅ Redeploy triggered — wait ~2 min then re-run test_e2e")
    else:
        print(f"  ❌ git push failed: {r2.stderr[:200]}")
        print("  → Go to Vercel dashboard and click 'Redeploy' manually.")


if __name__ == "__main__":
    main()
