"""Create a new RE agency Account in Zoho CRM."""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def create_account(account_name: str, phone: str = "", email: str = "") -> dict:
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    record = {"Account_Name": account_name}
    if phone:
        record["Phone"] = phone
    if email:
        record["Email"] = email

    resp = requests.post(
        f"{CRM_BASE}/Accounts",
        headers=headers,
        json={"data": [record]},
    )
    resp.raise_for_status()
    crm_id = resp.json()["data"][0]["details"]["id"]

    return {
        "id":           crm_id,
        "Account_Name": account_name,
        "Phone":        phone,
        "Email":        email,
    }


if __name__ == "__main__":
    a = create_account("Ray White Clayton", "03 9123 4567")
    print("Created:", a)
