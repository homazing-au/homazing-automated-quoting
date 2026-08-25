"""Fetch the Email field of a single Zoho CRM record (Accounts or Contacts)."""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def get_email(module: str, record_id: str) -> str:
    return get_field(module, record_id, "Email")


def get_field(module: str, record_id: str, field: str) -> str:
    if not record_id:
        return ""
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.get(f"{CRM_BASE}/{module}/{record_id}", headers=headers, params={"fields": field})
    if not resp.ok:
        return ""
    data = resp.json().get("data", [])
    return data[0].get(field, "") if data else ""
