"""Create a draft invoice in Zoho CRM Invoices module linked to a CRM Contact."""

import os
import requests
from datetime import date, timedelta
from tools.zoho_auth import get_access_token

CRM_BASE   = "https://www.zohoapis.com.au/crm/v2"
PRODUCT_ID = os.getenv("ZOHO_PRODUCT_ID", "124143000000580001")


def create_invoice(contact_id: str | None, pricing: dict, address: str = "", account_id: str = "") -> dict:
    """
    Args:
        contact_id: Zoho CRM Contact ID (property owner). None for realtor path (account only).
        pricing:    output from calculate_price()
        address:    property address used in the invoice Subject
        account_id: Zoho CRM Account ID (RE agency) to link the invoice to
    Returns:
        dict with invoice id and invoice_number
    """
    token   = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    # Set product unit price so CRM calculates GST correctly from the product tax
    requests.put(
        f"{CRM_BASE}/Products",
        headers=headers,
        json={"data": [{"id": PRODUCT_ID, "Unit_Price": pricing["subtotal_ex_gst"]}]},
    ).raise_for_status()

    subject = address if address else "Property Styling Invoice"
    today   = date.today()

    record = {
        "Subject":              subject,
        "Status":               "Draft",
        "Invoice_Date":         today.strftime("%Y-%m-%d"),
        "Due_Date":             (today + timedelta(days=14)).strftime("%Y-%m-%d"),
        "Terms_and_Conditions": "Due within 14 days. Prices include GST.",
        "Product_Details": [{
            "product":  {"id": PRODUCT_ID},
            "quantity": 1.0,
            "discount": 0.0,
        }],
    }
    if contact_id:
        record["Contact_Name"] = {"id": contact_id}
    if account_id:
        record["Account_Name"] = {"id": account_id}

    payload = {"data": [record]}

    resp = requests.post(f"{CRM_BASE}/Invoices", headers=headers, json=payload)
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} {resp.reason} — {resp.text}")

    result = resp.json()["data"][0]
    if result.get("status") == "error":
        raise RuntimeError(f"CRM error: {result.get('message')} — {result.get('details')}")

    invoice_id = result["details"]["id"]

    # CRM does not return the invoice number in the POST — fetch it separately
    get_resp = requests.get(
        f"{CRM_BASE}/Invoices/{invoice_id}",
        headers=headers,
        params={"fields": "Invoice_No"},
    )
    get_resp.raise_for_status()
    invoice_number = get_resp.json()["data"][0].get("Invoice_No", invoice_id)

    return {
        "id":             invoice_id,
        "invoice_number": invoice_number,
    }
