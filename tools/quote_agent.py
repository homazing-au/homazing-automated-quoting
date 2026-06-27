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


STAGE_ORDER = ["GET_ADDRESS", "COLLECT_ROOMS", "CONFIRM_ROOMS", "ASK_REFERRAL", "CONFIRM_PRICE", "GET_AGENT", "GET_AGENT_DETAILS"]

# Data keys to clear when reverting to each stage (clears that stage + all later stages)
STAGE_CLEAR_KEYS = {
    "GET_ADDRESS":       ["address"],
    "COLLECT_ROOMS":     ["rooms"],
    "CONFIRM_ROOMS":     [],
    "ASK_REFERRAL":      ["referral_pct", "pricing"],
    "CONFIRM_PRICE":     ["reduced_pct", "added_pct"],
    "GET_AGENT":         ["account_id", "agent_name", "agent_email"],
    "GET_AGENT_DETAILS": [],
}


def _session_file(chat_id: str) -> Path:
    return SESSION_DIR / f"session_{chat_id}.json"


def _load_session(chat_id: str) -> dict:
    f = _session_file(chat_id)
    if f.exists():
        return json.loads(f.read_text())
    return {"stage": "COLLECT_ROOMS", "data": {}}


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
            "ag":  data["agent_name"],
            "ae":  data.get("agent_email", ""),
            "pr":  data["pricing"],
            "rm":  data.get("rooms", {}),
            "addr": data.get("address", ""),
            "aid": data.get("account_id", ""),
            "did": quote.get("deal_id", ""),
        }, separators=(",", ":"))
        token = base64.urlsafe_b64encode(token_data.encode()).decode().rstrip("=")

        _save_quote_record(quote["quote_number"], {
            "quote_id":    quote["id"],
            "deal_id":     quote.get("deal_id", ""),
            "account_id":  data.get("account_id", ""),
            "agent_name":  data.get("agent_name", ""),
            "agent_email": data.get("agent_email", ""),
            "address":     data.get("address", ""),
            "rooms":       data.get("rooms", {}),
            "pricing":     data["pricing"],
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
                send_quote_email(
                    estimate_id=quote["id"],
                    to_email=agent_email,
                    agent_name=data["agent_name"],
                    quote_number=quote["quote_number"],
                    address=data.get("address", ""),
                    approval_url=approval_url,
                )
                email_status = f"Approval link emailed to {agent_email}"
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
            "ag":  data.get("agent_name", ""),
            "ae":  data.get("agent_email", ""),
            "pr":  new_pricing,
            "rm":  data.get("rooms", {}),
            "addr": data.get("address", ""),
            "aid": data.get("account_id", ""),
            "did": data.get("deal_id", ""),
        }, separators=(",", ":"))
        token = base64.urlsafe_b64encode(token_data.encode()).decode().rstrip("=")
        base_url = os.getenv("APPROVAL_BASE_URL", "https://homazing.com.au")
        approval_url = f"{base_url}/approve/{token}"

        _save_quote_record(quote_number, {
            "quote_id":    data["quote_id"],
            "deal_id":     data.get("deal_id", ""),
            "account_id":  data.get("account_id", ""),
            "agent_name":  data.get("agent_name", ""),
            "agent_email": data.get("agent_email", ""),
            "address":     data.get("address", ""),
            "rooms":       data.get("rooms", {}),
            "pricing":     new_pricing,
        })

        print(f"\nApproval URL: {approval_url}\n")
        (SESSION_DIR / "last_approval_url.txt").write_text(approval_url)

        agent_email = data.get("agent_email", "")
        email_status = ""
        if agent_email:
            try:
                send_quote_email(
                    estimate_id=data["quote_id"],
                    to_email=agent_email,
                    agent_name=data.get("agent_name", ""),
                    quote_number=quote_number,
                    address=data.get("address", ""),
                    approval_url=approval_url,
                )
                email_status = f"Updated approval link emailed to {agent_email}"
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


def handle_message(chat_id: str, text: str, reply_to_id: int | None = None) -> str:
    text = text.strip()

    if text.lower() in ("/start", "/new", "/reset"):
        _clear_session(chat_id)
        session = {"stage": "GET_ADDRESS", "data": {}}
        _save_session(chat_id, session)
        return "New quote started.\n\nWhat's the *property address*?"

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

        confirmed = _extract_yes_no(text)
        if confirmed is True:
            session["stage"] = "GET_AGENT"
            _save_session(chat_id, session)
            return "What's the RE agency name?"
        if confirmed is False:
            _clear_session(chat_id)
            return "Quote cancelled. Send /new to start again."

        return "Confirm the price? Or adjust with *reduce by X%* or *add X%*."

    # ── GET_AGENT ──────────────────────────────────────────────────────────────
    if stage == "GET_AGENT":
        from tools.zoho_lookup_contact import lookup_contact
        matches = lookup_contact(text)
        if matches:
            account = matches[0]
            data["account_id"] = account["id"]
            data["agent_name"] = account["Full_Name"]
            data["agent_email"] = account.get("Email", "")
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
