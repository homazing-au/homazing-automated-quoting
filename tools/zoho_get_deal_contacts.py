"""Resolve the people an SMS should go to for a given Zoho Deal.

- agent: the Deal's linked Account (Account_Name/Phone/Email).
- customer: the Deal's linked Contact - only present if the customer
  approved the quote themselves (that's when a Contact gets created). If the
  agent approved on the customer's behalf, no Contact exists, and callers
  should treat customer=None as "skip this recipient", not an error.
- assistant: the Account's Assistant_Name/Assistant_Mobile/Assistant_Email -
  optional per-agent fields, filled in manually when the account is set up.
"""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def _get(module: str, record_id: str, fields: list[str]) -> dict | None:
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.get(
        f"{CRM_BASE}/{module}/{record_id}",
        headers=headers,
        params={"fields": ",".join(fields)},
    )
    if resp.status_code in (204, 404):
        return None
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return data[0] if data else None


def get_deal_sms_contacts(deal_id: str) -> dict:
    """Returns {"agent": {...} | None, "customer": {...} | None,
    "assistant": {...} | None}, each a {"name", "mobile", "email"} dict."""
    result = {"agent": None, "customer": None, "assistant": None}

    deal = _get("Deals", deal_id, ["Account_Name", "Contact_Name"])
    if not deal:
        return result

    account_ref = deal.get("Account_Name")
    if account_ref:
        account = _get("Accounts", account_ref["id"], [
            "Account_Name", "Phone", "Email",
            "Assistant_Name", "Assistant_Mobile", "Assistant_Email",
        ])
        if account:
            result["agent"] = {
                "name":   account.get("Account_Name", ""),
                "mobile": account.get("Phone", ""),
                "email":  account.get("Email", ""),
            }
            if account.get("Assistant_Mobile"):
                result["assistant"] = {
                    "name":   account.get("Assistant_Name", ""),
                    "mobile": account.get("Assistant_Mobile", ""),
                    "email":  account.get("Assistant_Email", ""),
                }

    contact_ref = deal.get("Contact_Name")
    if contact_ref:
        contact = _get("Contacts", contact_ref["id"], ["Full_Name", "Mobile", "Email"])
        if contact:
            result["customer"] = {
                "name":   contact.get("Full_Name", ""),
                "mobile": contact.get("Mobile", ""),
                "email":  contact.get("Email", ""),
            }

    return result
