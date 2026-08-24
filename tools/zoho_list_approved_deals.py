"""List Zoho CRM Deals sitting in the 'Quote Approved' stage — approved
quotes that haven't been invoiced yet. Backs the Telegram bot's
'send invoice' command.
"""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def list_approved_deals(limit: int = 10) -> list[dict]:
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.get(
        f"{CRM_BASE}/Deals/search",
        headers=headers,
        params={"criteria": "(Stage:equals:Quote Approved)"},
    )
    if resp.status_code in (204, 404):
        return []
    resp.raise_for_status()
    deals = resp.json().get("data", [])
    deals.sort(key=lambda d: d.get("Modified_Time", ""), reverse=True)

    results = []
    for d in deals[:limit]:
        account = d.get("Account_Name") or {}
        contact = d.get("Contact_Name") or {}
        results.append({
            "id":           d.get("id"),
            "address":      d.get("Deal_Name", ""),
            "amount":       d.get("Amount", 0),
            "account_id":   account.get("id", ""),
            "account_name": account.get("name", ""),
            "contact_id":   contact.get("id", ""),
            "contact_name": contact.get("name", ""),
        })
    return results
