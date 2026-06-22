"""Look up RE agencies from Zoho CRM Accounts. Accounts are the source of truth for agencies."""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def lookup_contact(name: str) -> list[dict]:
    """Search CRM Accounts by name. Returns list of matches with normalised field names."""
    token = get_access_token()
    resp = requests.get(
        f"{CRM_BASE}/Accounts/search",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        params={"word": name},
    )
    if resp.status_code in (204, 404):
        return []
    resp.raise_for_status()
    search_lower = name.lower()
    return [
        {
            "id":        a.get("id"),
            "Full_Name": a.get("Account_Name", ""),
            "Email":     a.get("Email", ""),
            "Mobile":    a.get("Phone", ""),
        }
        for a in resp.json().get("data", [])
        if search_lower in a.get("Account_Name", "").lower()
    ]


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Ray White"
    results = lookup_contact(name)
    print(f"Found {len(results)} account(s):")
    for a in results:
        print(f"  {a['Full_Name']} | {a.get('Email')} | crm_id={a['id']}")
