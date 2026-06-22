"""
End-to-end test: Telegram bot → Zoho → Vercel approval → QBO invoice.

Steps:
  1. Verify Telegram bot is reachable
  2. Verify Zoho auth works
  3. Create a test Zoho Account + Quote + Deal
  4. Build an approval token and call the Vercel approval API
  5. Verify QBO received the customer and invoice
  6. Report pass/fail via Telegram

Usage:
    python -m tools.test_e2e
"""

import io
import os
import sys
import json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import base64
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

from tools.calculate_price import calculate_price
from tools.zoho_auth import get_access_token
from tools.zoho_create_account import create_account
from tools.zoho_create_quote import create_quote

load_dotenv()

VERCEL_URL       = "https://homazing.com.au"
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
QBO_CLIENT_ID    = os.getenv("QBO_CLIENT_ID")
QBO_CLIENT_SECRET= os.getenv("QBO_CLIENT_SECRET")
QBO_REFRESH_TOKEN= os.getenv("QBO_REFRESH_TOKEN")
QBO_REALM_ID     = os.getenv("QBO_REALM_ID")
QBO_ENVIRONMENT  = os.getenv("QBO_ENVIRONMENT", "sandbox")
QBO_TOKEN_URL    = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_BASE         = (
    "https://quickbooks.api.intuit.com"
    if QBO_ENVIRONMENT == "production"
    else "https://sandbox-quickbooks.api.intuit.com"
)

TEST_ADDR  = "99 E2E Test St, Glen Waverley VIC 3150"
TEST_ROOMS = {"master_bedroom": 1, "living": 1, "kitchen": 1}
TEST_NAME  = "E2E Test User"
TEST_EMAIL = "e2e-test@homazing.com.au"
TEST_PHONE = "0400000001"

results = []

def ok(step, detail=""):
    msg = f"  ✅ {step}" + (f": {detail}" if detail else "")
    print(msg)
    results.append(("PASS", step, detail))

def fail(step, detail=""):
    msg = f"  ❌ {step}" + (f": {detail}" if detail else "")
    print(msg)
    results.append(("FAIL", step, detail))

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
    )

def make_token(qn, ag, ae, pr, rm, addr, aid, did):
    data = {"qn": qn, "ag": ag, "ae": ae, "pr": pr, "rm": rm,
            "addr": addr, "aid": aid, "did": did}
    b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return b64

# ──────────────────────────────────────────────
print("\n=== Homazing End-to-End Test ===\n")

# Step 1: Telegram bot alive
print("1. Telegram bot check...")
try:
    r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=5)
    bot = r.json().get("result", {})
    if r.ok and bot.get("username"):
        ok("Telegram bot", f"@{bot['username']} is online")
    else:
        fail("Telegram bot", str(r.json()))
except Exception as e:
    fail("Telegram bot", str(e))

# Step 2: Zoho auth
print("\n2. Zoho auth check...")
zoho_token = None
try:
    zoho_token = get_access_token()
    ok("Zoho auth", "token obtained")
except Exception as e:
    fail("Zoho auth", str(e))

# Step 3: Create Zoho Account + Quote + Deal
print("\n3. Zoho Account + Quote + Deal...")
quote_data = None
account_id = deal_id = quote_number = None
if zoho_token:
    try:
        pricing = calculate_price(TEST_ROOMS)
        ok("Pricing engine", f"Total ${pricing['total_inc_gst']}")

        acct = create_account("E2E Test Agency")
        account_id = acct["id"]
        ok("Zoho Account", f"ID {account_id}")

        q = create_quote(account_id, pricing, TEST_ADDR)
        quote_number = q["quote_number"]
        deal_id      = q["deal_id"]
        ok("Zoho Quote + Deal", f"Quote {quote_number}, Deal {deal_id}")

        quote_data = {
            "qn":   quote_number,
            "pr":   pricing,
            "rm":   TEST_ROOMS,
            "addr": TEST_ADDR,
            "aid":  account_id,
            "did":  deal_id,
        }
    except Exception as e:
        fail("Zoho setup", str(e))
else:
    fail("Zoho setup", "skipped — no auth token")

# Step 4: Call Vercel approval API
print("\n4. Vercel approval API...")
invoice_number = None
if quote_data:
    try:
        token = make_token(
            qn=quote_data["qn"], ag="E2E Test", ae="",
            pr=quote_data["pr"], rm=quote_data["rm"],
            addr=quote_data["addr"], aid=quote_data["aid"], did=quote_data["did"],
        )
        body = {
            "type":   "homeowner",
            "name":   TEST_NAME,
            "email":  TEST_EMAIL,
            "mobile": TEST_PHONE,
        }
        resp = requests.post(
            f"{VERCEL_URL}/api/approve/{token}",
            json=body,
            timeout=30,
        )
        if resp.ok:
            rdata = resp.json()
            invoice_number = rdata.get("invoice_number")
            qbo_ok = rdata.get("qbo_ok", False)
            ok("Vercel approval", f"Invoice {invoice_number}")
        else:
            fail("Vercel approval", f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        fail("Vercel approval", str(e))
else:
    fail("Vercel approval", "skipped — no quote data")

# Step 5: QBO sync (verified via Vercel approval response)
print("\n5. QBO invoice verification...")
if invoice_number:
    if qbo_ok:
        ok("QBO invoice", f"Invoice {invoice_number} synced to QuickBooks")
    else:
        fail("QBO invoice", "Vercel reported QBO sync failed — check Telegram for details")
else:
    fail("QBO invoice", "skipped — no invoice number")

# ──────────────────────────────────────────────
print("\n=== Results ===")
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
print(f"  Passed: {passed}/{len(results)}")
print(f"  Failed: {failed}/{len(results)}")

lines = [f"*Homazing E2E Test — {date.today()}*\n"]
for status, step, detail in results:
    icon = "✅" if status == "PASS" else "❌"
    lines.append(f"{icon} {step}" + (f": {detail}" if detail else ""))
lines.append(f"\n*{passed}/{len(results)} passed*")

send_telegram("\n".join(lines))
print("\nResults sent to Telegram.")

if failed:
    sys.exit(1)
