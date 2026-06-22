"""Fetch recent Vercel deployment runtime logs for the approval route."""
import io, sys, json, os, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

TOKEN      = os.getenv("VERCEL_TOKEN", "")
PROJECT_ID = os.getenv("VERCEL_PROJECT_ID", "")
TEAM_ID    = os.getenv("VERCEL_TEAM_ID", "")

def api(path):
    req = urllib.request.Request(
        f"https://api.vercel.com{path}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# Get latest production deployment
deps = api(f"/v6/deployments?projectId={PROJECT_ID}&teamId={TEAM_ID}&limit=3&target=production")
deployments = deps.get("deployments", [])
if not deployments:
    print("No deployments found")
    exit()

dep = deployments[0]
dep_id  = dep["uid"]
dep_url = dep.get("url", "")
dep_state = dep.get("readyState", dep.get("state", ""))
print(f"Latest deployment: {dep_id}  state={dep_state}  url={dep_url}\n")

# Fetch runtime logs
try:
    logs_data = api(f"/v2/deployments/{dep_id}/events?teamId={TEAM_ID}&limit=100")
    events = logs_data if isinstance(logs_data, list) else logs_data.get("events", [])
    # Filter to error / relevant lines
    for e in events:
        text = e.get("text", "") or e.get("payload", {}).get("text", "")
        if any(k in text.lower() for k in ["error", "qbo", "redis", "upstash", "refresh", "token", "failed", "invalid"]):
            print(text)
except Exception as ex:
    print(f"Could not fetch logs: {ex}")
    # Try alternate endpoint
    try:
        logs2 = api(f"/v3/deployments/{dep_id}/events?teamId={TEAM_ID}")
        for e in (logs2 if isinstance(logs2, list) else []):
            text = e.get("text", "")
            if text:
                print(text)
    except Exception as ex2:
        print(f"Alternate also failed: {ex2}")
