"""Create a quote in Zoho CRM Quotes module linked to a CRM Account."""

import os
import requests
from datetime import date, timedelta
from tools.zoho_auth import get_access_token

CRM_BASE   = "https://www.zohoapis.com.au/crm/v2"
PRODUCT_ID = os.getenv("ZOHO_PRODUCT_ID", "124143000000580001")


def create_quote(account_id: str, pricing: dict, address: str = "", contact_id: str = "") -> dict:
    """
    Args:
        account_id: Zoho CRM Account ID (RE agency). Optional — omit for a direct
                    customer with no linked agency.
        pricing:    output from calculate_price()
        address:    property address used in the quote Subject
        contact_id: Zoho CRM Contact ID (customer), if this quote is for a
                    specific person rather than just the agency.
    Returns:
        dict with quote id and quote_number
    """
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    # Set product unit price so CRM calculates GST correctly from the product tax
    requests.put(
        f"{CRM_BASE}/Products",
        headers=headers,
        json={"data": [{"id": PRODUCT_ID, "Unit_Price": pricing["subtotal_ex_gst"]}]},
    ).raise_for_status()

    subject     = address if address else "Property Styling Quote"
    expiry_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    quote_record = {
        "Subject":              subject,
        "Quote_Stage":          "Draft",
        "Expiry_Date":          expiry_date,
        "Terms_and_Conditions": "Valid for 7 days. Prices include GST.",
        "Product_Details": [{
            "product":  {"id": PRODUCT_ID},
            "quantity": 1.0,
            "discount": 0.0,
        }],
    }
    if account_id:
        quote_record["Account_Name"] = {"id": account_id}
    if contact_id:
        quote_record["Contact_Name"] = {"id": contact_id}

    payload = {"data": [quote_record]}

    resp = requests.post(f"{CRM_BASE}/Quotes", headers=headers, json=payload)
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} {resp.reason} — {resp.text}")

    result = resp.json()["data"][0]
    if result.get("status") == "error":
        raise RuntimeError(f"CRM error: {result.get('message')} — {result.get('details')}")

    quote_id = result["details"]["id"]

    # CRM does not return the quote number in the POST — fetch it separately
    get_resp = requests.get(
        f"{CRM_BASE}/Quotes/{quote_id}",
        headers=headers,
        params={"fields": "Quote_Number"},
    )
    get_resp.raise_for_status()
    quote_number = get_resp.json()["data"][0].get("Quote_Number", quote_id)

    # Create a linked Deal to track the quote through the sales pipeline
    deal_record = {
        "Deal_Name":    subject,
        "Stage":        "Quote Awaiting Approval",
        "Closing_Date": expiry_date,
        "Amount":       pricing["total_inc_gst"],
    }
    if account_id:
        deal_record["Account_Name"] = {"id": account_id}
    if contact_id:
        deal_record["Contact_Name"] = {"id": contact_id}

    deal_payload = {"data": [deal_record]}
    deal_resp = requests.post(f"{CRM_BASE}/Deals", headers=headers, json=deal_payload)
    if not deal_resp.ok:
        raise RuntimeError(f"{deal_resp.status_code} {deal_resp.reason} — {deal_resp.text}")

    deal_result = deal_resp.json()["data"][0]
    if deal_result.get("status") == "error":
        raise RuntimeError(f"CRM error (Deal): {deal_result.get('message')} — {deal_result.get('details')}")

    deal_id = deal_result["details"]["id"]

    return {
        "id":           quote_id,
        "quote_number": quote_number,
        "deal_id":      deal_id,
    }


def get_quote_by_subject(subject: str) -> dict | None:
    """Find the most recently created Quote record whose Subject matches the
    given property address exactly (Subject is set to the address at
    creation time by create_quote above). Fallback for the 'resend quote'
    command when the local quote record (.tmp/quotes/*.json) is missing -
    that directory is disposable/ephemeral and doesn't survive a bot
    restart on Render, so Zoho is the durable source of truth here."""
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = requests.get(
        f"{CRM_BASE}/Quotes/search",
        headers=headers,
        params={"criteria": f"(Subject:equals:{subject})"},
    )
    if resp.status_code in (204, 404):
        return None
    resp.raise_for_status()
    records = resp.json().get("data", [])
    if not records:
        return None
    records.sort(key=lambda r: r.get("Created_Time", ""), reverse=True)
    top = records[0]
    return {"id": top.get("id"), "quote_number": top.get("Quote_Number", top.get("id"))}
