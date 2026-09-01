"""Thin wrapper around Twilio's SMS API.

Credentials come from .env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
TWILIO_FROM (a phone number, or the alphanumeric sender ID once Homazing's
is approved). Until those are set, send_sms() just logs what it would have
sent instead of failing - so this can be wired into every trigger point
now, and start actually sending the moment .env is filled in.

Never raises - an SMS failure should never block the sheet/Zoho update it's
attached to.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def _to_e164_au(number: str) -> str:
    """Zoho stores AU mobiles in local format ('0400 105 005'); Twilio
    requires E.164 ('+61400105005'). Leaves already-international numbers
    (starting with '+') untouched."""
    digits = "".join(c for c in number if c.isdigit() or c == "+")
    if digits.startswith("+"):
        return digits
    if digits.startswith("0"):
        return "+61" + digits[1:]
    return digits


def send_sms(to: str, body: str) -> None:
    if not to:
        return
    to = _to_e164_au(to)

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM")
    if not (sid and token and from_number):
        print(f"[sms] Twilio not configured yet - would send to {to}: {body!r}")
        return

    try:
        resp = requests.post(
            API_URL.format(sid=sid),
            auth=(sid, token),
            data={"To": to, "From": from_number, "Body": body},
            timeout=15,
        )
        if resp.status_code >= 300:
            print(f"[sms] Twilio send to {to} failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[sms] Twilio send to {to} raised: {e}")
