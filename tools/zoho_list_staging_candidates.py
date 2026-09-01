"""List Zoho CRM Deals that could still need staging: any deal that hasn't
reached Closed Won or Closed Lost. Staging can happen at any point in the
pipeline (awaiting approval, approved, or already invoiced) - the manual
"approved" stage update doesn't reliably line up with when a job actually
gets staged, so we treat every open stage as a candidate rather than relying
on a single stage value. Backs the Telegram bot's 'staging complete' command.
"""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"

OPEN_STAGES = ["Quote Awaiting Approval", "Quote Approved", "Invoiced"]


def list_staging_candidates() -> list[dict]:
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    criteria = "or".join(f"(Stage:equals:{stage})" for stage in OPEN_STAGES)
    resp = requests.get(
        f"{CRM_BASE}/Deals/search",
        headers=headers,
        params={"criteria": criteria},
    )
    if resp.status_code in (204, 404):
        return []
    resp.raise_for_status()
    deals = resp.json().get("data", [])

    results = []
    for d in deals:
        results.append({
            "id":      d.get("id"),
            "address": d.get("Deal_Name", ""),
            "stage":   d.get("Stage", ""),
        })
    return results
