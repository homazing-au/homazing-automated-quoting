"""
Homazing quote agent. Manages multi-turn Telegram conversation to collect
room details, calculate pricing, and create a Zoho CRM quote.

State machine: COLLECT_ROOMS → ASK_REFERRAL → CONFIRM_PRICE → ADJUST_PRICE
               → GET_AGENT → GET_AGENT_DETAILS → DONE
"""

import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from tools.calculate_price import calculate_price, mround, UNIT_COSTS, ROOM_LABELS

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
SESSION_DIR = Path(".tmp")
SESSION_DIR.mkdir(exist_ok=True)
QUOTES_DIR = SESSION_DIR / "quotes"
QUOTES_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = """You are a quoting assistant for Homazing, an Australian property styling company.
You help Manoj (the owner) create quotes via Telegram.

You extract structured data from natural, conversational messages.
Always respond with valid JSON only — no prose, no markdown, no explanation.

Room types and their keys:
- master_bedroom ($450), guest_bedroom ($350), kids_bedroom ($350), living ($450), dining ($350),
  kitchen ($100), alfresco ($150), bath ($50), hallway_table ($100),
  study ($300), small_living ($300)

Only extract rooms explicitly mentioned — do NOT add defaults like living, kitchen, dining, bath.
Map natural language like:
- "3 bed" → master_bedroom:1 + guest_bedroom:2 (plain extras, NOT kids)
- "kids bedroom"/"kids room"/"children's room" → kids_bedroom (only when "kids"/"children" mentioned)
- "2 living"/"extra living" → living:2, "lounge" → living, "ensuite"/"bathroom" → bath, "office" → study
- "alfresco"/"outdoor" → alfresco

All prices are inc. GST. GST = total ÷ 11. Subtotal ex-GST = total − GST.
MROUND rounds the total to nearest $10.
"""


STAGE_ORDER = [
    "GET_ADDRESS", "COLLECT_ROOMS", "CONFIRM_ROOMS", "ASK_REFERRAL", "CONFIRM_PRICE",
    "GET_AGENT", "GET_AGENT_DETAILS",
    "GET_CUSTOMER_DETAILS", "ASK_AGENCY_LINK", "GET_AGENCY_DETAILS_FOR_CUSTOMER",
]

# Data keys to clear when reverting to each stage (clears that stage + all later stages)
STAGE_CLEAR_KEYS = {
    "GET_ADDRESS":       ["address"],
    "COLLECT_ROOMS":     ["rooms"],
    "CONFIRM_ROOMS":     [],
    "ASK_REFERRAL":      ["referral_pct", "pricing"],
    "CONFIRM_PRICE":     ["reduced_pct", "added_pct"],
    "GET_AGENT":         ["account_id", "agent_name", "agent_email",
                           "customer_name", "customer_email", "customer_mobile", "agency_query"],
    "GET_AGENT_DETAILS": [],
    "GET_CUSTOMER_DETAILS":           ["customer_name", "customer_email", "customer_mobile"],
    "ASK_AGENCY_LINK":                ["account_id", "agent_name", "agent_email", "agency_query"],
    "GET_AGENCY_DETAILS_FOR_CUSTOMER": [],
}


def _session_file(chat_id: str) -> Path:
    return SESSION_DIR / f"session_{chat_id}.json"


def _load_session(chat_id: str) -> dict:
    f = _session_file(chat_id)
    if f.exists():
        return json.loads(f.read_text())
    return {"stage": "GET_ADDRESS", "data": {}}


def _save_session(chat_id: str, session: dict):
    _session_file(chat_id).write_text(json.dumps(session, indent=2))


def _clear_session(chat_id: str):
    f = _session_file(chat_id)
    if f.exists():
        f.unlink()


def _revert_session(session: dict, target_stage: str):
    """Revert to target_stage, clearing all data collected from that stage onwards."""
    try:
        idx = STAGE_ORDER.index(target_stage)
    except ValueError:
        return
    data = session.get("data", {})
    for stage in STAGE_ORDER[idx:]:
        for key in STAGE_CLEAR_KEYS.get(stage, []):
            data.pop(key, None)
    session["stage"] = target_stage


def _ask_claude(prompt: str) -> str:
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_rooms(text: str) -> dict | None:
    raw = _ask_claude(
        f"Extract room quantities from this message. Return JSON like "
        f'{{\"master_bedroom\": 1, \"living\": 1}}. Only include rooms mentioned. '
        f"Message: {text}"
    )
    try:
        rooms = json.loads(raw)
        return {k: int(v) for k, v in rooms.items() if k in UNIT_COSTS and int(v) > 0}
    except Exception:
        return None


def _extract_percentage(text: str) -> float | None:
    # Accept plain numbers like "10" or "5.5" or "10%" without needing Claude
    m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*%?\s*$', text.strip())
    if m:
        return float(m.group(1)) / 100
    raw = _ask_claude(
        f"Extract a percentage number from this message. Return JSON like {{\"pct\": 5.0}}. "
        f"If no percentage found, return {{\"pct\": null}}. Message: {text}"
    )
    try:
        val = json.loads(raw).get("pct")
        return float(val) / 100 if val is not None else None
    except Exception:
        return None


def _extract_yes_no(text: str) -> bool | None:
    raw = _ask_claude(
        f"Does this message mean yes/confirm/proceed or no/cancel? "
        f'Return JSON: {{"answer": "yes"}} or {{"answer": "no"}} or {{"answer": null}}. '
        f"Message: {text}"
    )
    try:
        val = json.loads(raw).get("answer")
        if val == "yes":
            return True
        if val == "no":
            return False
        return None
    except Exception:
        return None


def _extract_amount(text: str) -> float | None:
    m = re.search(r'(\d[\d,]*(?:\.\d+)?)', text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _quote_record_file(quote_number: str) -> Path:
    return QUOTES_DIR / f"{quote_number}.json"


def _save_quote_record(quote_number: str, record: dict):
    _quote_record_file(quote_number).write_text(json.dumps(record, indent=2))


def _load_quote_record(quote_number: str) -> dict | None:
    f = _quote_record_file(quote_number)
    if f.exists():
        return json.loads(f.read_text())
    return None


def _format_address(text: str) -> str:
    raw = _ask_claude(
        f"Format this Australian property address into: "
        f"\"Street Number Street Name, Suburb, STATE Postcode\". "
        f"Rules: title-case all words; abbreviated state in uppercase (VIC, NSW, QLD, SA, WA, TAS, ACT, NT); "
        f"add commas between street, suburb, and state+postcode; "
        f"infer state and postcode from suburb if not provided. "
        f"Return JSON only: {{\"formatted\": \"...\"}}. "
        f"Address: {text}"
    )
    try:
        return json.loads(raw).get("formatted") or text.title()
    except Exception:
        return text.title()


def _extract_agent_details(text: str) -> dict | None:
    raw = _ask_claude(
        f"Extract contact details from this message. "
        f'Return JSON: {{"name": "...", "email": "...", "mobile": "..."}}. '
        f"Use null for any missing field. Message: {text}"
    )
    try:
        return json.loads(raw)
    except Exception:
        return None


def _format_price_summary(pricing: dict) -> str:
    lines = []
    for item in pricing["line_items"]:
        lines.append(f"  {item['label']} ×{item['qty']} — ${item['amount']:,.0f}")
    lines.append(f"\n💰 *Total (inc. GST): ${pricing['total_inc_gst']:,.0f}*")
    lines.append(f"   GST: ${pricing['gst']:,.2f}")
    lines.append(f"   Ex-GST: ${pricing['subtotal_ex_gst']:,.2f}")
    if pricing["referral"]:
        lines.append(f"   Referral: ${pricing['referral']:,.2f}")
    if pricing["reduced"]:
        lines.append(f"   Discount: -${pricing['reduced']:,.2f}")
    return "\n".join(lines)


def _do_create_quote(chat_id: str, session: dict) -> str:
    from tools.zoho_create_quote import create_quote
    from tools.zoho_send_quote_email import send_quote_email
    import base64
    data = session["data"]
    try:
        quote = create_quote(data["account_id"], data["pricing"], data.get("address", ""))
        token_data = json.dumps({
            "qn":  quote["quote_number"],
            "qi":  quote["id"],
            "ag":  data["agent_name"],
            "ae":  data.get("agent_email", ""),
            "cu":  "",
            "cue": "",
            "pr":  data["pricing"],
            "rm":  data.get("rooms", {}),
            "addr": data.get("address", ""),
            "aid": data.get("account_id", ""),
            "did": quote.get("deal_id", ""),
            "cid": "",
        }, separators=(",", ":"))
        token = base64.urlsafe_b64encode(token_data.encode()).decode().rstrip("=")

        _save_quote_record(quote["quote_number"], {
            "quote_id":      quote["id"],
            "deal_id":       quote.get("deal_id", ""),
            "account_id":    data.get("account_id", ""),
            "contact_id":    "",
            "agent_name":    data.get("agent_name", ""),
            "agent_email":   data.get("agent_email", ""),
            "customer_name": "",
            "customer_email":"",
            "address":       data.get("address", ""),
            "rooms":         data.get("rooms", {}),
            "pricing":       data["pricing"],
        })

        _clear_session(chat_id)
        base_url = os.getenv("APPROVAL_BASE_URL", "https://homazing.com.au")
        approval_url = f"{base_url}/approve/{token}"

        print(f"\nApproval URL: {approval_url}\n")
        (SESSION_DIR / "last_approval_url.txt").write_text(approval_url)

        # Send email to agent if we have their email
        agent_email = data.get("agent_email", "")
        email_status = ""
        if agent_email:
            try:
                from tools.zoho_get_email import get_field
                assistant_email = get_field("Accounts", data.get("account_id", ""), "Assistant_Email")
                send_quote_email(
                    estimate_id=quote["id"],
                    to_emails=[agent_email],
                    agent_name=data["agent_name"],
                    quote_number=quote["quote_number"],
                    address=data.get("address", ""),
                    approval_url=approval_url,
                    cc_emails=[assistant_email] if assistant_email else None,
                )
                email_status = f"Approval link emailed to {agent_email}"
                try:
                    from tools.google_sheets import append_staging_job
                    append_staging_job(
                        address=data.get("address", ""),
                        agency=data.get("account_site") or data.get("agent_name", ""),
                        agent_name=data.get("agent_name", ""),
                        gross=data["pricing"]["total_inc_gst"],
                        has_referral=bool(data.get("referral_pct")),
                    )
                except Exception as sheet_err:
                    print(f"Staging Jobs sheet append failed: {sheet_err}")
            except Exception as email_err:
                print(f"Email send failed: {email_err}")
                email_status = f"Email failed: {email_err}"
        else:
            email_status = "No email on file"

        return (
            f"Quote created in Zoho\n"
            f"Quote: {quote['quote_number']}\n"
            f"Agent: {data['agent_name']}\n"
            f"Total: ${data['pricing']['total_inc_gst']:,.0f} inc GST\n\n"
            f"{email_status}"
        )
    except Exception as e:
        return f"Quote creation failed: {e}\nSend /new to try again."


def _do_create_customer_quote(chat_id: str, session: dict) -> str:
    """Create a quote for a direct customer, optionally linked to an existing RE agency Account."""
    from tools.zoho_create_quote import create_quote
    from tools.zoho_create_contact import create_contact
    from tools.zoho_send_quote_email import send_quote_email
    import base64
    data = session["data"]
    try:
        account_id = data.get("account_id", "")
        contact = create_contact(
            data["customer_name"],
            data.get("customer_email", ""),
            data.get("customer_mobile", ""),
            account_id=account_id,
        )
        quote = create_quote(account_id, data["pricing"], data.get("address", ""), contact_id=contact["id"])

        token_data = json.dumps({
            "qn":  quote["quote_number"],
            "qi":  quote["id"],
            "ag":  data.get("agent_name", ""),
            "ae":  data.get("agent_email", ""),
            "cu":  data["customer_name"],
            "cue": data.get("customer_email", ""),
            "pr":  data["pricing"],
            "rm":  data.get("rooms", {}),
            "addr": data.get("address", ""),
            "aid": account_id,
            "did": quote.get("deal_id", ""),
            "cid": contact["id"],
        }, separators=(",", ":"))
        token = base64.urlsafe_b64encode(token_data.encode()).decode().rstrip("=")

        _save_quote_record(quote["quote_number"], {
            "quote_id":      quote["id"],
            "deal_id":       quote.get("deal_id", ""),
            "account_id":    account_id,
            "contact_id":    contact["id"],
            "agent_name":    data.get("agent_name", ""),
            "agent_email":   data.get("agent_email", ""),
            "customer_name": data["customer_name"],
            "customer_email":data.get("customer_email", ""),
            "address":       data.get("address", ""),
            "rooms":         data.get("rooms", {}),
            "pricing":       data["pricing"],
        })

        _clear_session(chat_id)
        base_url = os.getenv("APPROVAL_BASE_URL", "https://homazing.com.au")
        approval_url = f"{base_url}/approve/{token}"

        print(f"\nApproval URL: {approval_url}\n")
        (SESSION_DIR / "last_approval_url.txt").write_text(approval_url)

        to_emails = [e for e in (data.get("customer_email", ""), data.get("agent_email", "")) if e]
        email_status = ""
        if to_emails:
            try:
                from tools.zoho_get_email import get_field
                assistant_email = get_field("Accounts", account_id, "Assistant_Email")
                send_quote_email(
                    estimate_id=quote["id"],
                    to_emails=to_emails,
                    agent_name=data["customer_name"],
                    quote_number=quote["quote_number"],
                    address=data.get("address", ""),
                    approval_url=approval_url,
                    cc_emails=[assistant_email] if assistant_email else None,
                )
                email_status = f"Approval link emailed to {', '.join(to_emails)}"
                try:
                    from tools.google_sheets import append_staging_job
                    append_staging_job(
                        address=data.get("address", ""),
                        agency=data.get("account_site") or data.get("agent_name", ""),
                        agent_name=data["customer_name"],
                        gross=data["pricing"]["total_inc_gst"],
                        has_referral=bool(data.get("referral_pct")),
                    )
                except Exception as sheet_err:
                    print(f"Staging Jobs sheet append failed: {sheet_err}")
            except Exception as email_err:
                print(f"Email send failed: {email_err}")
                email_status = f"Email failed: {email_err}"
        else:
            email_status = "No email on file"

        agency_line = f"Agency: {data['agent_name']}\n" if data.get("agent_name") else "Agency: Direct (none)\n"
        return (
            f"Quote created in Zoho\n"
            f"Quote: {quote['quote_number']}\n"
            f"Customer: {data['customer_name']}\n"
            f"{agency_line}"
            f"Total: ${data['pricing']['total_inc_gst']:,.0f} inc GST\n\n"
            f"{email_status}"
        )
    except Exception as e:
        return f"Quote creation failed: {e}\nSend /new to try again."


def _start_edit_quote(chat_id: str, quote_number: str) -> str:
    record = _load_quote_record(quote_number)
    if not record:
        return f"Quote *{quote_number}* not found. Check the quote number and try again."

    session = {"stage": "EDIT_AMOUNT", "data": {**record, "quote_number": quote_number}}
    _save_session(chat_id, session)
    total = record["pricing"]["total_inc_gst"]
    return (
        f"Editing *{quote_number}*.\n"
        f"Current total: ${total:,.0f} inc GST.\n\n"
        f"What's the new total (inc. GST)?"
    )


def _do_resend_quote(chat_id: str, session: dict, new_pricing: dict) -> str:
    from tools.zoho_update_quote import update_quote_amount
    from tools.zoho_send_quote_email import send_quote_email
    import base64
    data = session["data"]
    quote_number = data["quote_number"]
    try:
        update_quote_amount(data["quote_id"], data.get("deal_id", ""), new_pricing)

        token_data = json.dumps({
            "qn":  quote_number,
            "qi":  data.get("quote_id", ""),
            "ag":  data.get("agent_name", ""),
            "ae":  data.get("agent_email", ""),
            "cu":  data.get("customer_name", ""),
            "cue": data.get("customer_email", ""),
            "pr":  new_pricing,
            "rm":  data.get("rooms", {}),
            "addr": data.get("address", ""),
            "aid": data.get("account_id", ""),
            "did": data.get("deal_id", ""),
            "cid": data.get("contact_id", ""),
        }, separators=(",", ":"))
        token = base64.urlsafe_b64encode(token_data.encode()).decode().rstrip("=")
        base_url = os.getenv("APPROVAL_BASE_URL", "https://homazing.com.au")
        approval_url = f"{base_url}/approve/{token}"

        _save_quote_record(quote_number, {
            "quote_id":      data["quote_id"],
            "deal_id":       data.get("deal_id", ""),
            "account_id":    data.get("account_id", ""),
            "contact_id":    data.get("contact_id", ""),
            "agent_name":    data.get("agent_name", ""),
            "agent_email":   data.get("agent_email", ""),
            "customer_name": data.get("customer_name", ""),
            "customer_email":data.get("customer_email", ""),
            "address":       data.get("address", ""),
            "rooms":         data.get("rooms", {}),
            "pricing":       new_pricing,
        })

        print(f"\nApproval URL: {approval_url}\n")
        (SESSION_DIR / "last_approval_url.txt").write_text(approval_url)

        to_emails = [e for e in (data.get("customer_email", ""), data.get("agent_email", "")) if e]
        email_status = ""
        if to_emails:
            try:
                from tools.zoho_get_email import get_field
                assistant_email = get_field("Accounts", data.get("account_id", ""), "Assistant_Email")
                send_quote_email(
                    estimate_id=data["quote_id"],
                    to_emails=to_emails,
                    agent_name=data.get("customer_name") or data.get("agent_name", ""),
                    quote_number=quote_number,
                    address=data.get("address", ""),
                    approval_url=approval_url,
                    cc_emails=[assistant_email] if assistant_email else None,
                )
                email_status = f"Updated approval link emailed to {', '.join(to_emails)}"
            except Exception as email_err:
                print(f"Email send failed: {email_err}")
                email_status = f"Email failed — send manually"
        else:
            email_status = "No email on file"

        _clear_session(chat_id)
        return (
            f"Quote *{quote_number}* updated.\n"
            f"New total: ${new_pricing['total_inc_gst']:,.0f} inc GST\n\n"
            f"{email_status}"
        )
    except Exception as e:
        return f"Quote update failed: {e}"


def _start_send_invoice(chat_id: str) -> str:
    from tools.zoho_list_approved_deals import list_approved_deals
    deals = list_approved_deals()
    if not deals:
        return "No approved quotes are waiting to be invoiced."

    session = {"stage": "SEND_INVOICE_PICK", "data": {"invoice_candidates": deals}}
    _save_session(chat_id, session)
    lines = [f"{i + 1}. {d['address']}" for i, d in enumerate(deals)]
    return "Which job do you want to invoice? Reply with the number:\n\n" + "\n".join(lines)


def _do_send_invoice(deal: dict) -> str:
    """Trigger the actual invoice (Zoho + QuickBooks + email) via the homazing-website
    API — that's where the QBO sync and PDF/email logic already live, same as the
    system that used to fire automatically on approval. This just moves *when* it fires.
    """
    import requests
    base_url = os.getenv("APPROVAL_BASE_URL", "https://homazing.com.au")
    secret = os.getenv("CRON_SECRET", "")
    try:
        resp = requests.post(
            f"{base_url}/api/send-invoice",
            headers={"Authorization": f"Bearer {secret}"},
            json={"deal_id": deal["id"]},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if "error" in result:
            return f"Invoice creation failed: {result['error']}"

        email_status = (
            f"Invoice emailed to {', '.join(result.get('to_emails', []))}"
            if result.get("email_sent") else "No email on file — send manually"
        )
        qbo_status = "Synced to QuickBooks" if result.get("qbo_ok") else "QuickBooks sync failed — check Telegram alert"

        invoice_number = result.get("invoice_number")
        sheet_status = ""
        if invoice_number:
            try:
                from tools.google_sheets import set_invoice_number
                sheet_result = set_invoice_number(deal["address"], invoice_number)
                if sheet_result.get("row") is None:
                    sheet_status = f"\n(Sheet not updated: {sheet_result.get('reason')})"
            except Exception as e:
                sheet_status = f"\n(Sheet not updated: {e})"

        return (
            f"Invoice *{result.get('invoice_number', '?')}* created for {deal['address']}\n"
            f"Total: ${deal['amount']:,.0f} inc GST\n\n"
            f"{email_status}\n"
            f"{qbo_status}"
            f"{sheet_status}"
        )
    except Exception as e:
        return f"Invoice creation failed: {e}"


_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _extract_numbers(text: str) -> list[int]:
    """Pull list-item numbers out of free text, digits or spelled out -
    'referral paid for number one' and 'referral paid for 2,4' both work."""
    lowered = text.lower()
    found = [(m.start(), int(m.group())) for m in re.finditer(r"\d+", lowered)]
    for word, val in _WORD_NUMBERS.items():
        for m in re.finditer(rf"\b{word}\b", lowered):
            found.append((m.start(), val))
    found.sort(key=lambda x: x[0])
    return [n for _, n in found]


def _first_name(full_name: str) -> str:
    return full_name.split()[0] if full_name and full_name.split() else "there"


def _notify_staging_event(deal_id: str, address: str, event: str) -> None:
    """event: 'staged' or 'removed'. Texts agent, customer (if a Contact
    exists - it won't if the agent approved the quote on the customer's
    behalf), and assistant (if the account has one on file) - the assistant
    gets a shorter, purely factual version. Best-effort: no deal_id, no
    contact, or no mobile number just means that recipient is silently
    skipped."""
    if not deal_id:
        return
    from tools.zoho_get_deal_contacts import get_deal_sms_contacts
    from tools.twilio_sms import send_sms
    contacts = get_deal_sms_contacts(deal_id)
    for role in ("agent", "customer", "assistant"):
        contact = contacts.get(role)
        if not (contact and contact.get("mobile")):
            continue
        first = _first_name(contact.get("name", ""))
        if role == "assistant":
            body = (
                f"Hi {first}, the styling is complete at {address} and ready for photos. Thank you!"
                if event == "staged" else
                f"Hi {first}, the furniture styling has been removed from {address}. Thank you!"
            )
        else:
            body = (
                f"Hi {first}, the styling is complete at {address} and ready for photos. "
                f"Thanks for choosing Homazing, wishing you all the best with the sale!"
                if event == "staged" else
                f"Hi {first}, congratulations on the sale! The furniture styling has been removed "
                f"from {address}. Thanks again for choosing Homazing."
            )
        send_sms(contact["mobile"], body)


def _notify_referral_paid(deal_id: str, address: str) -> None:
    """Texts the agent only, once their referral is marked paid."""
    if not deal_id:
        return
    from tools.zoho_get_deal_contacts import get_deal_sms_contacts
    from tools.twilio_sms import send_sms
    agent = get_deal_sms_contacts(deal_id).get("agent")
    if agent and agent.get("mobile"):
        first = _first_name(agent.get("name", ""))
        send_sms(
            agent["mobile"],
            f"Hi {first}, your referral payment for {address} has been sent. "
            f"Thanks so much for the business, we really appreciate it!",
        )


def _start_staging_complete(chat_id: str) -> str:
    from tools.sheet_actions import list_staging_complete_candidates
    candidates = list_staging_complete_candidates()
    if not candidates:
        return "No jobs waiting to be marked as staged today."
    session = {"stage": "STAGING_COMPLETE_PICK", "data": {"candidates": candidates}}
    _save_session(chat_id, session)
    lines = [f"{i + 1}. {c['address']}" for i, c in enumerate(candidates)]
    return "Which address(es) were staged today? Reply with the number(s), e.g. *2* or *2,4*:\n\n" + "\n".join(lines)


def _start_staging_removed(chat_id: str) -> str:
    from tools.sheet_actions import list_staging_removed_candidates
    candidates = list_staging_removed_candidates()
    if not candidates:
        return "No currently-staged jobs waiting to be marked as removed."
    session = {"stage": "STAGING_REMOVED_PICK", "data": {"candidates": candidates}}
    _save_session(chat_id, session)
    lines = [f"{i + 1}. {c['address']}" for i, c in enumerate(candidates)]
    return "Which address(es) had staging removed today? Reply with the number(s), e.g. *2* or *2,4*:\n\n" + "\n".join(lines)


def _start_referral_list(chat_id: str) -> str:
    from tools.sheet_actions import list_referral_candidates
    candidates = list_referral_candidates()
    if not candidates:
        return "No outstanding referrals to pay."
    session = {"stage": "REFERRAL_ACTIVE", "data": {"candidates": candidates, "last_asked": None}}
    _save_session(chat_id, session)
    lines = [f"{i + 1}. {c['address']} - {c['amount_display']}" for i, c in enumerate(candidates)]
    return (
        "Outstanding referrals:\n\n" + "\n".join(lines) +
        "\n\nSay *how much for 2*, *referral paid for 2*, or just *paid* after asking how much."
    )


def _start_new_quote(chat_id: str) -> str:
    _clear_session(chat_id)
    _save_session(chat_id, {"stage": "GET_ADDRESS", "data": {}})
    return "New quote started.\n\nWhat's the *property address*?"


# Numbered menu shown on a greeting/help message, in display order.
# Each entry: (label, function(chat_id) -> reply text that starts that flow).
MENU_ITEMS = [
    ("New quote", _start_new_quote),
    ("Send invoice", _start_send_invoice),
    ("Staging complete", _start_staging_complete),
    ("Staging removed", _start_staging_removed),
    ("Referral", _start_referral_list),
]


def _start_help_menu(chat_id: str) -> str:
    session = {"stage": "HELP_MENU_PICK", "data": {}}
    _save_session(chat_id, session)
    lines = [f"{i + 1}. {label}" for i, (label, _) in enumerate(MENU_ITEMS)]
    return "What do you want to do?\n\n" + "\n".join(lines) + "\n\nReply with a number."


def handle_message(chat_id: str, text: str, reply_to_id: int | None = None) -> str:
    text = text.strip()

    if text.lower() in ("/start", "/new", "/reset"):
        return _start_new_quote(chat_id)

    if text.lower() in ("/invoice", "send invoice", "invoice"):
        return _start_send_invoice(chat_id)

    normalized = text.lower().lstrip("/").replace("_", " ").strip()

    if normalized == "staging complete":
        return _start_staging_complete(chat_id)

    if normalized == "staging removed":
        return _start_staging_removed(chat_id)

    if normalized in ("referral", "referrals", "referral list", "list referrals"):
        return _start_referral_list(chat_id)

    if normalized in ("hi", "hello", "hey", "help", "menu", "commands", "what can you do"):
        return _start_help_menu(chat_id)

    edit_match = re.match(r'^/?edit\s+(\S+)', text, re.IGNORECASE)
    if edit_match:
        return _start_edit_quote(chat_id, edit_match.group(1))

    session = _load_session(chat_id)

    # If user replied to a specific bot message, revert to that stage
    if reply_to_id:
        target_stage = session.get("msg_map", {}).get(str(reply_to_id))
        if target_stage:
            _revert_session(session, target_stage)
            _save_session(chat_id, session)

    stage = session["stage"]
    data = session["data"]

    # ── GET_ADDRESS ────────────────────────────────────────────────────────────
    if stage == "GET_ADDRESS":
        data["address"] = _format_address(text)
        session["stage"] = "COLLECT_ROOMS"
        _save_session(chat_id, session)
        return (
            f"Got it: *{data['address']}*\n\n"
            f"How many bedrooms? Any alfresco or extra living areas?\n"
            f"e.g. *3 bed*, *3 bed 1 kids, 1 alfresco*, *4 bed, 2 living*\n\n"
            f"_(1 living, 1 dining, 1 kitchen, 1 bath, 1 hallway included by default)_\n\n"
            f"_💡 To edit the address later, reply directly to this message._"
        )

    # ── COLLECT_ROOMS ──────────────────────────────────────────────────────────
    ROOM_DEFAULTS = {"living": 1, "kitchen": 1, "dining": 1, "bath": 1, "hallway_table": 1}

    if stage == "COLLECT_ROOMS":
        rooms = _extract_rooms(text)
        if not rooms:
            return "I couldn't make out the bedrooms. Try something like: *3 bed* or *3 bed, 1 alfresco*"
        # Apply defaults for rooms not mentioned
        for key, qty in ROOM_DEFAULTS.items():
            if key not in rooms:
                rooms[key] = qty
        data["rooms"] = rooms
        session["stage"] = "CONFIRM_ROOMS"
        _save_session(chat_id, session)

        room_list = "\n".join(f"  • {ROOM_LABELS[k]} ×{v}" for k, v in rooms.items())
        return (
            f"Got it:\n{room_list}\n\n"
            f"OK to proceed? _(or reply to this message to edit rooms)_"
        )

    # ── CONFIRM_ROOMS ──────────────────────────────────────────────────────────
    if stage == "CONFIRM_ROOMS":
        confirmed = _extract_yes_no(text)
        if confirmed is False:
            session["stage"] = "COLLECT_ROOMS"
            _save_session(chat_id, session)
            return "No problem. How many rooms? e.g. *3 bed* or *3 bed, 1 alfresco*"
        if confirmed is True or text.lower() in ("ok", "okay", "yes", "yep", "sure", "correct"):
            session["stage"] = "ASK_REFERRAL"
            _save_session(chat_id, session)
            return "Is there a referral on this job? If so, what %? (or say *no*)"
        # Any other text — re-ask
        return "Reply *OK* to confirm the rooms, or *no* to re-enter them."

    # ── ASK_REFERRAL ───────────────────────────────────────────────────────────
    if stage == "ASK_REFERRAL":
        answer = _extract_yes_no(text)
        pct = _extract_percentage(text)

        if pct is not None:
            data["referral_pct"] = pct
        elif answer is False:
            data["referral_pct"] = 0.0
        else:
            return "Is there a referral? Reply with a % like *5%* or say *no*."

        pricing = calculate_price(data["rooms"], referral_pct=data["referral_pct"])
        data["pricing"] = pricing
        session["stage"] = "CONFIRM_PRICE"
        _save_session(chat_id, session)

        summary = _format_price_summary(pricing)
        return f"{summary}\n\nConfirm? Or say *reduce by X%* / *add X%* to adjust."

    # ── CONFIRM_PRICE / ADJUST_PRICE ───────────────────────────────────────────
    if stage in ("CONFIRM_PRICE", "ADJUST_PRICE"):
        # Check for adjustment first
        reduce_match = re.search(r"reduc\w*\s+by\s+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
        add_match    = re.search(r"add\s+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)

        if reduce_match:
            data["reduced_pct"] = float(reduce_match.group(1)) / 100
            pricing = calculate_price(
                data["rooms"],
                referral_pct=data.get("referral_pct", 0),
                reduced_pct=data["reduced_pct"],
                added_pct=data.get("added_pct", 0),
            )
            data["pricing"] = pricing
            session["stage"] = "CONFIRM_PRICE"
            _save_session(chat_id, session)
            summary = _format_price_summary(pricing)
            return f"Revised:\n{summary}\n\nConfirm?"

        if add_match:
            data["added_pct"] = float(add_match.group(1)) / 100
            pricing = calculate_price(
                data["rooms"],
                referral_pct=data.get("referral_pct", 0),
                reduced_pct=data.get("reduced_pct", 0),
                added_pct=data["added_pct"],
            )
            data["pricing"] = pricing
            session["stage"] = "CONFIRM_PRICE"
            _save_session(chat_id, session)
            summary = _format_price_summary(pricing)
            return f"Revised:\n{summary}\n\nConfirm?"

        # Flat dollar override — e.g. "make it 2400" / "$2,400" / "set to 2500"
        if "%" not in text:
            flat_total = _extract_amount(text)
            if flat_total and flat_total > 100:
                new_total = mround(flat_total, 10)
                pricing = data["pricing"]
                gst = round(new_total / 11, 2)
                subtotal_ex_gst = round(new_total - gst, 2)
                delta = new_total - pricing["total_inc_gst"]
                added   = pricing.get("added", 0)
                reduced = pricing.get("reduced", 0)
                if delta >= 0:
                    added += delta
                else:
                    reduced += -delta
                new_pricing = {
                    **pricing,
                    "total_inc_gst":   new_total,
                    "gst":             gst,
                    "subtotal_ex_gst": subtotal_ex_gst,
                    "added":           round(added, 2),
                    "reduced":         round(reduced, 2),
                }
                data["pricing"] = new_pricing
                session["stage"] = "CONFIRM_PRICE"
                _save_session(chat_id, session)
                summary = _format_price_summary(new_pricing)
                return f"Revised:\n{summary}\n\nConfirm?"

        confirmed = _extract_yes_no(text)
        if confirmed is True:
            session["stage"] = "GET_AGENT"
            _save_session(chat_id, session)
            return "What's the RE agency name? _(or reply \"customer\" if this is a direct customer)_"
        if confirmed is False:
            _clear_session(chat_id)
            return "Quote cancelled. Send /new to start again."

        return "Confirm the price? Or adjust with *reduce by X%*, *add X%*, or type a flat amount like *2400*."

    # ── GET_AGENT ──────────────────────────────────────────────────────────────
    if stage == "GET_AGENT":
        if text.strip().lower() in ("customer", "direct customer", "direct"):
            session["stage"] = "GET_CUSTOMER_DETAILS"
            _save_session(chat_id, session)
            return (
                "Please provide the customer's name, mobile and email — e.g.\n"
                "_John Smith, 0412 345 678, john@gmail.com_"
            )

        from tools.zoho_lookup_contact import lookup_contact
        matches = lookup_contact(text)
        if matches:
            account = matches[0]
            data["account_id"] = account["id"]
            data["agent_name"] = account["Full_Name"]
            data["agent_email"] = account.get("Email", "")
            data["account_site"] = account.get("Account_Site", "")
            session["data"] = data
            _save_session(chat_id, session)
            return (
                f"Found *{account['Full_Name']}*.\n"
                + _do_create_quote(chat_id, session)
            )
        else:
            data["agent_name"] = text
            session["stage"] = "GET_AGENT_DETAILS"
            _save_session(chat_id, session)
            return (
                f"*{text}* not found in Zoho.\n"
                f"Please provide their name, mobile and email — e.g.\n"
                f"_Jane Smith, 0412 345 678, jane@raywhite.com_"
            )

    # ── GET_AGENT_DETAILS — create new Account ─────────────────────────────────
    if stage == "GET_AGENT_DETAILS":
        from tools.zoho_create_account import create_account
        details = _extract_agent_details(text)
        if not details or not details.get("name"):
            return "Please provide their name, mobile and email — e.g. _Jane Smith, 0412 345 678, jane@raywhite.com_"
        account = create_account(details["name"], details.get("mobile", ""), details.get("email", ""))
        data["account_id"] = account["id"]
        data["agent_name"] = account["Account_Name"]
        data["agent_email"] = details.get("email", "")
        session["data"] = data
        _save_session(chat_id, session)
        return f"Account created for *{account['Account_Name']}*.\n" + _do_create_quote(chat_id, session)

    # ── GET_CUSTOMER_DETAILS — direct customer, not going through an agency form ─
    if stage == "GET_CUSTOMER_DETAILS":
        details = _extract_agent_details(text)
        if not details or not details.get("name"):
            return "Please provide the customer's name, mobile and email — e.g. _John Smith, 0412 345 678, john@gmail.com_"
        data["customer_name"] = details["name"]
        data["customer_email"] = details.get("email") or ""
        data["customer_mobile"] = details.get("mobile") or ""
        session["stage"] = "ASK_AGENCY_LINK"
        _save_session(chat_id, session)
        return (
            f"Got it: *{data['customer_name']}*.\n\n"
            f"Is this linked to an existing RE agency? Reply with the agency name, or say *no*."
        )

    # ── ASK_AGENCY_LINK — is the direct customer sourced from an agency? ────────
    if stage == "ASK_AGENCY_LINK":
        if text.strip().lower() in ("no", "none", "n/a", "na", "nope", "nah"):
            data["account_id"] = ""
            data["agent_name"] = ""
            data["agent_email"] = ""
            session["data"] = data
            _save_session(chat_id, session)
            return _do_create_customer_quote(chat_id, session)

        from tools.zoho_lookup_contact import lookup_contact
        matches = lookup_contact(text)
        if matches:
            account = matches[0]
            data["account_id"] = account["id"]
            data["agent_name"] = account["Full_Name"]
            data["agent_email"] = account.get("Email", "")
            data["account_site"] = account.get("Account_Site", "")
            session["data"] = data
            _save_session(chat_id, session)
            return (
                f"Linked to *{account['Full_Name']}*.\n"
                + _do_create_customer_quote(chat_id, session)
            )
        else:
            data["agency_query"] = text
            session["stage"] = "GET_AGENCY_DETAILS_FOR_CUSTOMER"
            _save_session(chat_id, session)
            return (
                f"*{text}* not found in Zoho.\n"
                f"Please provide their name, mobile and email — e.g.\n"
                f"_Jane Smith, 0412 345 678, jane@raywhite.com_"
            )

    # ── GET_AGENCY_DETAILS_FOR_CUSTOMER — new Account for a direct customer's agency
    if stage == "GET_AGENCY_DETAILS_FOR_CUSTOMER":
        from tools.zoho_create_account import create_account
        details = _extract_agent_details(text)
        if not details or not details.get("name"):
            return "Please provide their name, mobile and email — e.g. _Jane Smith, 0412 345 678, jane@raywhite.com_"
        account = create_account(details["name"], details.get("mobile", ""), details.get("email", ""))
        data["account_id"] = account["id"]
        data["agent_name"] = account["Account_Name"]
        data["agent_email"] = details.get("email") or ""
        session["data"] = data
        _save_session(chat_id, session)
        return f"Agency account created for *{account['Account_Name']}*.\n" + _do_create_customer_quote(chat_id, session)

    # ── SEND_INVOICE_PICK — pick which approved job to invoice ──────────────────
    if stage == "SEND_INVOICE_PICK":
        candidates = data.get("invoice_candidates", [])
        m = re.match(r'^\s*(\d+)\s*$', text)
        if not m:
            return "Please reply with just the number of the job to invoice."
        idx = int(m.group(1)) - 1
        if idx < 0 or idx >= len(candidates):
            return f"Please reply with a number between 1 and {len(candidates)}."
        deal = candidates[idx]
        _clear_session(chat_id)
        return _do_send_invoice(deal)

    # ── HELP_MENU_PICK — numbered menu from "hi"/"help" ──────────────────────────
    if stage == "HELP_MENU_PICK":
        nums = _extract_numbers(text)
        if not nums:
            return "Please reply with just the number of what you want to do."
        idx = nums[0] - 1
        if idx < 0 or idx >= len(MENU_ITEMS):
            return f"Please reply with a number between 1 and {len(MENU_ITEMS)}."
        _, start_fn = MENU_ITEMS[idx]
        return start_fn(chat_id)

    # ── STAGING_COMPLETE_PICK — mark today as the Staged Date ───────────────────
    if stage == "STAGING_COMPLETE_PICK":
        from tools.sheet_actions import mark_staged
        candidates = data.get("candidates", [])
        nums = _extract_numbers(text)
        if not nums:
            return "Please reply with the number(s) of the address(es), e.g. *2* or *2,4*."
        indices = [int(n) - 1 for n in nums]
        if any(i < 0 or i >= len(candidates) for i in indices):
            return f"Please reply with number(s) between 1 and {len(candidates)}."
        done = []
        for i in indices:
            c = candidates[i]
            mark_staged(c["row"])
            _notify_staging_event(c.get("deal_id", ""), c["address"], "staged")
            done.append(c["address"])
        _clear_session(chat_id)
        return "Marked as staged today:\n" + "\n".join(f"• {a}" for a in done)

    # ── STAGING_REMOVED_PICK — mark today as the Staging Removed Date ───────────
    if stage == "STAGING_REMOVED_PICK":
        from tools.sheet_actions import mark_staging_removed
        candidates = data.get("candidates", [])
        nums = _extract_numbers(text)
        if not nums:
            return "Please reply with the number(s) of the address(es), e.g. *2* or *2,4*."
        indices = [int(n) - 1 for n in nums]
        if any(i < 0 or i >= len(candidates) for i in indices):
            return f"Please reply with number(s) between 1 and {len(candidates)}."
        done = []
        for i in indices:
            c = candidates[i]
            mark_staging_removed(c["row"])
            _notify_staging_event(c.get("deal_id", ""), c["address"], "removed")
            done.append(c["address"])
        _clear_session(chat_id)
        return "Marked staging removed today:\n" + "\n".join(f"• {a}" for a in done)

    # ── REFERRAL_ACTIVE — "how much for N" / "referral paid for N" / bare "paid" ─
    if stage == "REFERRAL_ACTIVE":
        from tools.sheet_actions import mark_referral_paid, get_referral_amount_display
        candidates = data.get("candidates", [])
        lowered = text.lower().strip()

        def _candidate_from_text(t):
            nums = _extract_numbers(t)
            if not nums:
                return None
            idx = nums[0] - 1
            if idx < 0 or idx >= len(candidates):
                return None
            return candidates[idx]

        if lowered in ("paid", "yes paid", "mark paid"):
            last_idx = data.get("last_asked")
            if last_idx is None:
                return "Paid for which one? Ask *how much for N* first, or say *referral paid for N*."
            c = candidates[last_idx]
            mark_referral_paid(c["row"], c.get("deal_id", ""))
            _notify_referral_paid(c.get("deal_id", ""), c["address"])
            return f"Marked referral paid for {c['address']}."

        if "how much" in lowered:
            c = _candidate_from_text(lowered)
            if not c:
                return "How much for which number? e.g. *how much for 2*"
            data["last_asked"] = candidates.index(c)
            session["data"] = data
            _save_session(chat_id, session)
            amount = get_referral_amount_display(c["row"])
            return f"Referral for {c['address']}: {amount}"

        if "referral" in lowered and "paid" in lowered:
            c = _candidate_from_text(lowered)
            if not c:
                return "Referral paid for which number? e.g. *referral paid for 2*"
            mark_referral_paid(c["row"], c.get("deal_id", ""))
            _notify_referral_paid(c.get("deal_id", ""), c["address"])
            return f"Marked referral paid for {c['address']}."

        return (
            "Say *how much for N*, *referral paid for N*, or *paid* (after asking how much).\n"
            "Send */referral* again to see the list."
        )

    # ── EDIT_AMOUNT — renegotiated price on an already-sent quote ───────────────
    if stage == "EDIT_AMOUNT":
        new_total = _extract_amount(text)
        if new_total is None:
            return "Please provide the new total as a number, e.g. *2400* or *$2,400*."
        new_total = mround(new_total, 10)
        pricing = data["pricing"]
        gst = round(new_total / 11, 2)
        subtotal_ex_gst = round(new_total - gst, 2)
        delta = new_total - pricing["total_inc_gst"]
        added   = pricing.get("added", 0)
        reduced = pricing.get("reduced", 0)
        if delta >= 0:
            added += delta
        else:
            reduced += -delta
        new_pricing = {
            **pricing,
            "total_inc_gst":   new_total,
            "gst":             gst,
            "subtotal_ex_gst": subtotal_ex_gst,
            "added":           round(added, 2),
            "reduced":         round(reduced, 2),
        }
        return _do_resend_quote(chat_id, session, new_pricing)

    # ── CREATE_QUOTE (fallback — should be reached via _do_create_quote) ────────
    if stage == "CREATE_QUOTE":
        return _do_create_quote(chat_id, session)

    return "Something went wrong. Send /new to start again."
