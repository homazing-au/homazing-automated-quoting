"""Push the current local QBO_REFRESH_TOKEN into Upstash Redis using the pipeline format."""
import io, sys, json, os, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

REDIS_URL     = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN   = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
QBO_RT        = os.getenv("QBO_REFRESH_TOKEN", "")

if not REDIS_URL or not REDIS_TOKEN:
    print("ERROR: UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN not set"); sys.exit(1)
if not QBO_RT:
    print("ERROR: QBO_REFRESH_TOKEN not set in .env"); sys.exit(1)

today = __import__("datetime").date.today().isoformat()
commands = [
    ["SET", "QBO_REFRESH_TOKEN", QBO_RT],
    ["SET", "QBO_TOKEN_ISSUED",  today],
]

req = urllib.request.Request(
    f"{REDIS_URL}/pipeline",
    data=json.dumps(commands).encode(),
    headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    print(f"Redis pipeline result: {result}")
    if all(item.get("result") == "OK" for item in result):
        print("OK — QBO_REFRESH_TOKEN and QBO_TOKEN_ISSUED seeded into Redis")
    else:
        print("WARNING: unexpected result — check above")
except urllib.error.HTTPError as e:
    print(f"ERROR {e.code}: {e.read()[:300]}")
