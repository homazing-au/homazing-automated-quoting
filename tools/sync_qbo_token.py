"""
Pull the current QBO_REFRESH_TOKEN from Vercel and update local .env.
Uses `vercel env pull` (the only way to decrypt encrypted Vercel env vars).
Run this if the local token is stale after a Vercel approval rotated it.
"""

import os, re, subprocess, tempfile
from dotenv import load_dotenv

ENV_PATH    = os.path.join(os.path.dirname(__file__), "..", ".env")
WEBSITE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "homazing-website")


def main():
    # Pull all Vercel production env vars into a temp file
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False)
    tmp.close()
    try:
        result = subprocess.run(
            f'npx vercel env pull "{tmp.name}" --environment production --yes',
            shell=True, capture_output=True, text=True, cwd=WEBSITE_DIR,
        )
        if result.returncode != 0:
            print("ERROR: vercel env pull failed:", result.stderr[:200])
            return

        # Parse QBO_REFRESH_TOKEN from the pulled file
        with open(tmp.name, "r", encoding="utf-8", errors="replace") as f:
            pulled = f.read()

        m = re.search(r"^QBO_REFRESH_TOKEN=(.+)$", pulled, flags=re.MULTILINE)
        if not m:
            print("ERROR: QBO_REFRESH_TOKEN not found in Vercel env pull output")
            return

        new_token = m.group(1).strip().strip('"')
        if not new_token:
            print("ERROR: QBO_REFRESH_TOKEN is empty in Vercel")
            return

        # Write it into local .env
        with open(ENV_PATH, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        pattern = r"^QBO_REFRESH_TOKEN=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, f"QBO_REFRESH_TOKEN={new_token}", content, flags=re.MULTILINE)
        else:
            content += f"\nQBO_REFRESH_TOKEN={new_token}\n"

        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        print("OK — local .env QBO_REFRESH_TOKEN synced from Vercel")

    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


if __name__ == "__main__":
    main()
