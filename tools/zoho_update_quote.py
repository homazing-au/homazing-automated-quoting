"""Update an existing Zoho CRM Quote's price and the linked Deal's Amount.

Used when a client negotiates the price after a quote has been sent —
updates the Quote's product line so its totals recalculate, and syncs
the linked Deal's Amount to match.
"""

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"


def update_quote_amount(quote_id: str, deal_id: str, pricing: dict) -> None:
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    # Fetch the existing Product_Details line so we can update it by id
    get_resp = requests.get(
        f"{CRM_BASE}/Quotes/{quote_id}",
        headers=headers,
        params={"fields": "Product_Details"},
    )
    get_resp.raise_for_status()
    lines = get_resp.json()["data"][0].get("Product_Details", [])
    if not lines:
        raise RuntimeError(f"Quote {quote_id} has no Product_Details to update")

    line = lines[0]
    updated_line = {
        "id":         line["id"],
        "product":    {"id": line["product"]["id"]},
        "quantity":   1.0,
        "unit_price": pricing["subtotal_ex_gst"],
        "discount":   0.0,
    }

    resp = requests.put(
        f"{CRM_BASE}/Quotes/{quote_id}",
        headers=headers,
        json={"data": [{"id": quote_id, "Product_Details": [updated_line]}]},
    )
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} {resp.reason} — {resp.text}")
    result = resp.json()["data"][0]
    if result.get("status") == "error":
        raise RuntimeError(f"CRM error (Quote update): {result.get('message')} — {result.get('details')}")

    if deal_id:
        deal_resp = requests.put(
            f"{CRM_BASE}/Deals",
            headers=headers,
            json={"data": [{"id": deal_id, "Amount": pricing["total_inc_gst"]}]},
        )
        if not deal_resp.ok:
            raise RuntimeError(f"{deal_resp.status_code} {deal_resp.reason} — {deal_resp.text}")
        deal_result = deal_resp.json()["data"][0]
        if deal_result.get("status") == "error":
            raise RuntimeError(f"CRM error (Deal update): {deal_result.get('message')} — {deal_result.get('details')}")
