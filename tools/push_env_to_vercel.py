"""
Push QBO env vars from local .env to Vercel Production.
Usage: python -m tools.push_env_to_vercel
"""
import os
import shutil
import subprocess
from dotenv import load_dotenv

load_dotenv()

WEBSITE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "homazing-website"))
NPX = shutil.which("npx") or "npx"

KEYS = [
    "QBO_CLIENT_ID",
    "QBO_CLIENT_SECRET",
    "QBO_REFRESH_TOKEN",
    "QBO_REALM_ID",
    "QBO_ENVIRONMENT",
]

print(f"Pushing QBO vars to Vercel (from local .env) ...\n")

for key in KEYS:
    val = os.getenv(key)
    if not val:
        print(f"  SKIP  {key} (not set in .env)")
        continue

    # Remove existing (ignore errors if not present)
    subprocess.run([NPX, "vercel", "env", "rm", key, "production", "--yes"],
                   cwd=WEBSITE_DIR, capture_output=True)

    # Add with value from .env
    proc = subprocess.run(
        [NPX, "vercel", "env", "add", key, "production"],
        input=val + "\n",
        text=True,
        cwd=WEBSITE_DIR,
        capture_output=True,
    )
    if proc.returncode == 0:
        display = val[:8] + "..." if len(val) > 8 else val
        print(f"  OK    {key} = {display}")
    else:
        print(f"  FAIL  {key}: {proc.stderr.strip()[:120]}")

print("\nDone. Triggering redeploy...")
subprocess.run(["git", "commit", "--allow-empty", "-m", "chore: sync QBO env vars"],
               cwd=WEBSITE_DIR, capture_output=True)
subprocess.run(["git", "push"], cwd=WEBSITE_DIR, capture_output=True)
print("Redeploy triggered.")
