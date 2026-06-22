"""Check recent QBO invoices and whether invoice 1211 exists."""
import os, requests
from dotenv import load_dotenv
load_dotenv()

tr = requests.post("https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    auth=(os.getenv("QBO_CLIENT_ID"), os.getenv("QBO_CLIENT_SECRET")),
    headers={"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded"},
    data={"grant_type":"refresh_token","refresh_token":os.getenv("QBO_REFRESH_TOKEN")})
token = tr.json()["access_token"]
env   = os.getenv("QBO_ENVIRONMENT","sandbox")
base  = "https://quickbooks.api.intuit.com" if env=="production" else "https://sandbox-quickbooks.api.intuit.com"
realm = os.getenv("QBO_REALM_ID")
h     = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

r = requests.get(f"{base}/v3/company/{realm}/query", headers=h,
    params={"query": "select DocNumber,TotalAmt,TxnDate from Invoice order by MetaData.CreateTime desc startposition 1 maxresults 10"})
print("Last 10 QBO invoices:")
for inv in r.json().get("QueryResponse",{}).get("Invoice",[]):
    print(f"  DocNumber={inv['DocNumber']}  Amount=${inv.get('TotalAmt')}  Date={inv.get('TxnDate')}")
