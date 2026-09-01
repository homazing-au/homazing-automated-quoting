"""List Zoho CRM Deals in the 'Invoiced' stage. Backs the Telegram bot's
'staging removed' command - staging only gets picked up once the job has
been invoiced.
"""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def list_invoiced_deals() -> list[dict]:
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.get(
        f"{CRM_BASE}/Deals/search",
        headers=headers,
        params={"criteria": "(Stage:equals:Invoiced)"},
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
        })
    return results
