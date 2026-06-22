"""Create a new contact in Zoho CRM, optionally linked to an Account (RE agency)."""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def create_contact(full_name: str, email: str, mobile: str, account_id: str = "") -> dict:
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    name_parts = full_name.strip().split(" ", 1)
    record = {
        "First_Name": name_parts[0] if len(name_parts) > 1 else "",
        "Last_Name":  name_parts[-1],
        "Email":      email,
        "Mobile":     mobile,
    }
    if account_id:
        record["Account_Name"] = {"id": account_id}

    resp = requests.post(
        f"{CRM_BASE}/Contacts",
        headers=headers,
        json={"data": [record]},
    )
    resp.raise_for_status()
    result = resp.json()["data"][0]
    crm_id = result["details"]["id"]

    # Zoho returns DUPLICATE_DATA (HTTP 200) when a contact with the same email exists.
    # In that case, update the existing contact so the Account_Name link is applied.
    if result.get("code") == "DUPLICATE_DATA" and account_id:
        requests.put(
            f"{CRM_BASE}/Contacts",
            headers=headers,
            json={"data": [{"id": crm_id, "Account_Name": {"id": account_id}}]},
        )

    return {
        "id":        crm_id,
        "Full_Name": full_name,
        "Email":     email,
        "Mobile":    mobile,
    }


if __name__ == "__main__":
    c = create_contact("Jane Smith", "jane@example.com", "0412345678")
    print("Created:", c)
