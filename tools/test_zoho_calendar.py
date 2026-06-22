"""
Quick test: create a Zoho CRM calendar event for tomorrow.
Usage: python tools/test_zoho_calendar.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import requests
from zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"
DATE     = "2026-06-18"  # tomorrow
TITLE    = "72 McMahons Rd, Ferntree Gully VIC 3156"  # test property address

token = get_access_token()

record = {
    "Event_Title":    TITLE,
    "Start_DateTime": f"{DATE}T08:00:00+10:00",
    "End_DateTime":   f"{DATE}T17:00:00+10:00",
    "All_day":        True,
    "Venue":          TITLE,
}

res = requests.post(
    f"{CRM_BASE}/Events",
    headers={
        "Authorization":  f"Zoho-oauthtoken {token}",
        "Content-Type":   "application/json",
    },
    json={"data": [record]},
)

print("Status:", res.status_code)
print(res.json())
