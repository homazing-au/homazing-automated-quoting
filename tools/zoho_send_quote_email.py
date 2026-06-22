"""Send approval email via Zoho Mail SMTP and mark CRM quote stage as Delivered."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from tools.zoho_auth import get_access_token

CRM_BASE = "https://www.zohoapis.com.au/crm/v2"
ADMIN_EMAIL = "admin@homazing.com.au"


def send_quote_email(
    estimate_id: str,
    to_email: str,
    agent_name: str,
    quote_number: str,
    address: str,
    approval_url: str,
) -> None:
    first_name = agent_name.strip().split()[0] if agent_name.strip() else agent_name
    link_label = f"Property styling quote for {address}"

    plain = (
        f"Hi {first_name},\n\n"
        f"Thank you for choosing Homazing. Please find your property styling quote below.\n\n"
        f"To review and approve your quote, click the link below:\n"
        f"{link_label}\n"
        f"{approval_url}\n\n"
        f"This quote is valid for 14 days. To accept, simply open the link, "
        f"fill in your details, and click Approve.\n\n"
        f"If you have any questions, please don't hesitate to get in touch.\n\n"
        f"Kind regards,\n"
        f"The Homazing Team"
    )

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#2C2825;line-height:1.6;">
  <p>Hi {first_name},</p>
  <p>Thank you for choosing Homazing. Please find your property styling quote below.</p>
  <p>To review and approve your quote, click the link below:</p>
  <p>
    <a href="{approval_url}" style="color:#8B7355;font-weight:500;">{link_label}</a>
  </p>
  <p>This quote is valid for 14 days. To accept, simply open the link, fill in your details, and click Approve.</p>
  <p>If you have any questions, please don't hesitate to get in touch.</p>
  <p>Kind regards,<br>The Homazing Team</p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    msg["Subject"] = f"Homazing Quote - {address}"
    msg["From"]    = os.getenv("EMAIL_FROM", "Homazing <admin@homazing.com.au>")
    msg["To"]      = to_email
    msg["Cc"]      = ADMIN_EMAIL

    host     = os.getenv("EMAIL_HOST", "smtp.zoho.com.au")
    port     = int(os.getenv("EMAIL_PORT", 587))
    user     = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(msg["From"], [to_email, ADMIN_EMAIL], msg.as_string())

    # Mark CRM quote stage as Delivered
    token = get_access_token()
    requests.put(
        f"{CRM_BASE}/Quotes/{estimate_id}",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        json={"data": [{"id": estimate_id, "Quote_Stage": "Delivered"}]},
    ).raise_for_status()
