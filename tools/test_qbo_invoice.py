"""
Test QBO invoice creation directly (no Vercel).
- Amounts are: Inclusive of Tax
- GST column: GST (10%)
- Rate: total_inc_gst
- Qty: 1
"""
import io, sys, json, os, base64, urllib.request, urllib.parse, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

REDIS_URL    = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN  = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
CLIENT_ID    = os.getenv("QBO_CLIENT_ID", "")
CLIENT_SECRET= os.getenv("QBO_CLIENT_SECRET", "")
REALM_ID     = os.getenv("QBO_REALM_ID", "")
QBO_ENV      = os.getenv("QBO_ENVIRONMENT", "production")
BASE_URL     = (
    f"https://quickbooks.api.intuit.com/v3/company/{REALM_ID}"
    if QBO_ENV == "production"
    else f"https://sandbox-quickbooks.api.intuit.com/v3/company/{REALM_ID}"
)

def qbo_request(path, method="GET", body=None, access_token=""):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Accept", "application/json")
    if body:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# ── Step 1: Get access token from Redis ──────────────────────────────────────
print("1. Getting QBO access token from Redis...")
req = urllib.request.Request(
    f"{REDIS_URL}/get/QBO_REFRESH_TOKEN",
    headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
)
with urllib.request.urlopen(req) as r:
    refresh_token = json.loads(r.read()).get("result", "")

if not refresh_token:
    refresh_token = os.getenv("QBO_REFRESH_TOKEN", "")

auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
token_req = urllib.request.Request(
    "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode(),
    headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    method="POST",
)
with urllib.request.urlopen(token_req) as r:
    token_data = json.loads(r.read())

access_token = token_data.get("access_token", "")
if not access_token:
    print(f"   FAIL: {token_data}")
    sys.exit(1)
print("   OK — access token obtained")

# ── Step 2: List available tax codes ─────────────────────────────────────────
print("\n2. Querying QBO tax codes...")
status, data = qbo_request(
    f"/query?query={urllib.parse.quote('select * from TaxCode')}",
    access_token=access_token,
)
tax_codes = data.get("QueryResponse", {}).get("TaxCode", [])
if tax_codes:
    for tc in tax_codes:
        print(f"   Id={tc.get('Id')!r:6} Name={tc.get('Name')!r:30} Active={tc.get('Active')}")
else:
    print(f"   HTTP {status}: {json.dumps(data)[:300]}")

# ── Step 3: Find the GST (10%) tax code ──────────────────────────────────────
gst_code = None
for tc in tax_codes:
    name = tc.get("Name", "").upper()
    if "GST" in name and tc.get("Active"):
        gst_code = tc
        break

if gst_code:
    print(f"\n   Using tax code: Id={gst_code['Id']!r}, Name={gst_code['Name']!r}")
else:
    print("\n   WARNING: no active GST tax code found — will try Id='GST'")

tax_code_id = gst_code["Id"] if gst_code else "GST"

# ── Step 4: Create a test invoice ─────────────────────────────────────────────
print("\n3. Creating test QBO invoice...")
TEST_DOC    = "E2E-DIRECT-01"
TEST_AMOUNT = 1000.00  # $1,000 inc GST

# Pick first customer
status_c, cdata = qbo_request(
    f"/query?query={urllib.parse.quote('select * from Customer maxresults 1')}",
    access_token=access_token,
)
customers   = cdata.get("QueryResponse", {}).get("Customer", [])
customer_id = customers[0]["Id"] if customers else "1"
print(f"   Using customer Id={customer_id!r}")

import datetime
today = datetime.date.today().isoformat()
due   = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

invoice_body = {
    "DocNumber": TEST_DOC,
    "CustomerRef": {"value": customer_id},
    "TxnDate": today,
    "DueDate": due,
    "GlobalTaxCalculation": "TaxInclusive",
    "Line": [
        {
            "DetailType": "SalesItemLineDetail",
            "Amount": TEST_AMOUNT,
            "SalesItemLineDetail": {
                "ItemRef":    {"value": "1", "name": "Services"},
                "UnitPrice":  TEST_AMOUNT,
                "Qty":        1,
                "TaxCodeRef": {"value": tax_code_id},
            },
        }
    ],
}

status_i, idata = qbo_request("/invoice", method="POST", body=invoice_body, access_token=access_token)
print(f"   HTTP {status_i}")
if status_i in (200, 201):
    inv = idata.get("Invoice", {})
    print(f"   ✅ Invoice created: Id={inv.get('Id')}, DocNumber={inv.get('DocNumber')}")
else:
    fault = idata.get("Fault", {})
    for err in fault.get("Error", []):
        print(f"   ❌ Code {err.get('code')}: {err.get('Detail')}")
    print(f"   Raw: {json.dumps(idata)[:500]}")
