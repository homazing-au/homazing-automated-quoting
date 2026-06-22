"""
Test that:
1. The QBO_REFRESH_TOKEN in Upstash Redis is readable
2. That token is valid (exchanges for an access token with Intuit)
Does NOT print any token values.
"""
import io, sys, json, os, base64, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

REDIS_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
QBO_ID      = os.getenv("QBO_CLIENT_ID", "")
QBO_SECRET  = os.getenv("QBO_CLIENT_SECRET", "")
QBO_ENV_TOKEN = os.getenv("QBO_REFRESH_TOKEN", "")

print("=== Redis + QBO Token Test ===\n")

# Step 1: Read token from Redis
print("1. Reading QBO_REFRESH_TOKEN from Redis...")
if not REDIS_URL or not REDIS_TOKEN:
    print("   ERROR: UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN not set in .env")
    sys.exit(1)

try:
    req = urllib.request.Request(
        f"{REDIS_URL}/get/QBO_REFRESH_TOKEN",
        headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    redis_token = data.get("result")
    if redis_token:
        print(f"   OK — token found in Redis (length: {len(redis_token)} chars)")
    else:
        print("   ERROR: token is null/empty in Redis")
        sys.exit(1)
except Exception as e:
    print(f"   ERROR reading from Redis: {e}")
    sys.exit(1)

# Step 2: Compare with local .env token
if QBO_ENV_TOKEN:
    if redis_token == QBO_ENV_TOKEN:
        print("   Redis token matches local .env token")
    else:
        print("   WARNING: Redis token differs from local .env token")
        print("   (This is expected if the token rotated since last setup)")

# Step 3: Test Redis token against QBO
print("\n2. Testing Redis token against QuickBooks...")
try:
    auth = base64.b64encode(f"{QBO_ID}:{QBO_SECRET}".encode()).decode()
    req2 = urllib.request.Request(
        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        data=f"grant_type=refresh_token&refresh_token={urllib.parse.quote(redis_token)}".encode(),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    import urllib.parse
    req2 = urllib.request.Request(
        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": redis_token}).encode(),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req2) as r:
        resp = json.loads(r.read())
    if resp.get("access_token"):
        new_rt = resp.get("refresh_token", "")
        print("   OK — access token obtained from QBO")
        if new_rt and new_rt != redis_token:
            print("   Token rotated — updating Redis with new token...")
            set_req = urllib.request.Request(
                f"{REDIS_URL}/set/QBO_REFRESH_TOKEN",
                data=json.dumps(["SET", "QBO_REFRESH_TOKEN", new_rt]).encode(),
                headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
                method="POST",
            )
            # Use pipeline format
            pipe_req = urllib.request.Request(
                f"{REDIS_URL}/pipeline",
                data=json.dumps([["SET", "QBO_REFRESH_TOKEN", new_rt]]).encode(),
                headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(pipe_req) as r2:
                result = json.loads(r2.read())
                print(f"   Redis updated: {result}")
            # Also update local .env
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            import re
            with open(env_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            content = re.sub(r"^QBO_REFRESH_TOKEN=.*$", f"QBO_REFRESH_TOKEN={new_rt}", content, flags=re.MULTILINE)
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("   Local .env updated with new token")
        print("\n✅ PASS — Redis token is valid and works with QBO")
    else:
        print(f"   FAIL — QBO rejected the token: {resp.get('error')} / {resp.get('error_description','')}")
except urllib.error.HTTPError as e:
    err = e.read().decode(errors="replace")
    print(f"   FAIL — HTTP {e.code}: {err[:300]}")
except Exception as e:
    print(f"   ERROR: {e}")
