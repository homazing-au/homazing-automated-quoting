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


def mark_quote_approved(quote_id: str, deal_id: str, contact_id: str = "") -> None:
    """Called when the customer/agent approves the quote on the web page.
    Moves the Quote to 'Confirmed' and the Deal to 'Quote Approved' — does NOT
    raise an invoice. Invoicing is a separate, manually-triggered step via the
    Telegram bot's 'send invoice' command, so jobs aren't invoiced before the
    work is actually scheduled/done.
    """
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    if quote_id:
        resp = requests.put(
            f"{CRM_BASE}/Quotes",
            headers=headers,
            json={"data": [{"id": quote_id, "Quote_Stage": "Confirmed"}]},
        )
        resp.raise_for_status()

    if deal_id:
        deal_record = {"id": deal_id, "Stage": "Quote Approved"}
        if contact_id:
            deal_record["Contact_Name"] = {"id": contact_id}
        resp2 = requests.put(f"{CRM_BASE}/Deals", headers=headers, json={"data": [deal_record]})
        resp2.raise_for_status()


def mark_deal_invoiced(deal_id: str) -> None:
    """Called after an invoice has actually been created and sent for a Deal."""
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.put(
        f"{CRM_BASE}/Deals",
        headers=headers,
        json={"data": [{"id": deal_id, "Stage": "Invoiced"}]},
    )
    resp.raise_for_status()


def mark_deal_closed_won(deal_id: str) -> None:
    """Called once the referral on an invoiced Deal has been paid - the last
    step in the pipeline, so the Deal moves to 'Closed Won'."""
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.put(
        f"{CRM_BASE}/Deals",
        headers=headers,
        json={"data": [{"id": deal_id, "Stage": "Closed Won"}]},
    )
    resp.raise_for_status()


def mark_deal_closed_lost(deal_id: str) -> None:
    """Called when a customer/agent declines a quote still in 'Quote
    Awaiting Approval' - the deal never converts, so it moves to
    'Closed Lost'."""
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.put(
        f"{CRM_BASE}/Deals",
        headers=headers,
        json={"data": [{"id": deal_id, "Stage": "Closed Lost"}]},
    )
    resp.raise_for_status()
