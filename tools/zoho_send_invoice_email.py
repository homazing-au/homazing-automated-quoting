"""Send invoice email with PDF attachment to the property owner (contact) via SMTP."""

import os
import smtplib
from datetime import date, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from tools.generate_invoice_pdf import generate_invoice_pdf

ADMIN_EMAIL = "admin@homazing.com.au"


def send_invoice_email(
    to_email: str,
    contact_name: str,
    invoice_number: str,
    address: str,
    total_inc_gst: float,
    pricing: dict | None = None,
) -> None:
    first_name = contact_name.strip().split()[0] if contact_name.strip() else contact_name
    due_date   = (date.today() + timedelta(days=14)).strftime("%#d %B %Y")

    plain = (
        f"Hi {first_name},\n\n"
        f"Thank you for approving your property styling quote. "
        f"Please find your invoice details below.\n\n"
        f"Invoice Number : {invoice_number}\n"
        f"Property       : {address}\n"
        f"Amount Due     : ${total_inc_gst:,.0f} (inc. GST)\n"
        f"Payment Due    : {due_date}\n\n"
        f"Payment Details:\n"
        f"  Account Name: Homazing\n"
        f"  Bank: —\n"
        f"  BSB: —\n"
        f"  Account Number: —\n"
        f"  Reference: {invoice_number}\n\n"
        f"Please use your invoice number as the payment reference and send "
        f"a remittance confirmation once payment has been made.\n\n"
        f"If you have any questions, please don't hesitate to get in touch.\n\n"
        f"Kind regards,\n"
        f"The Homazing Team\n"
        f"admin@homazing.com.au | +61 499 040 301"
    )

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#2C2825;line-height:1.6;">
  <p>Hi {first_name},</p>
  <p>Thank you for approving your property styling quote.
     Please find your invoice attached, along with the details below.</p>
  <table style="border-collapse:collapse;margin:12px 0;">
    <tr><td style="padding:4px 16px 4px 0;color:#6B6259;">Invoice Number</td><td><strong>{invoice_number}</strong></td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#6B6259;">Property</td><td>{address}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#6B6259;">Amount Due</td><td><strong>${total_inc_gst:,.0f} (inc. GST)</strong></td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#6B6259;">Payment Due</td><td>{due_date}</td></tr>
  </table>
  <p style="margin-top:16px;"><strong>Payment Details</strong></p>
  <table style="border-collapse:collapse;margin:4px 0;">
    <tr><td style="padding:3px 16px 3px 0;color:#6B6259;">Account Name</td><td>Homazing</td></tr>
    <tr><td style="padding:3px 16px 3px 0;color:#6B6259;">Bank</td><td>—</td></tr>
    <tr><td style="padding:3px 16px 3px 0;color:#6B6259;">BSB</td><td>—</td></tr>
    <tr><td style="padding:3px 16px 3px 0;color:#6B6259;">Account Number</td><td>—</td></tr>
    <tr><td style="padding:3px 16px 3px 0;color:#6B6259;">Reference</td><td>{invoice_number}</td></tr>
  </table>
  <p style="margin-top:16px;">Please use your invoice number as the payment reference and send
     a remittance confirmation once payment has been made.</p>
  <p>If you have any questions, please don't hesitate to get in touch.</p>
  <p>Kind regards,<br>The Homazing Team<br>
     <a href="mailto:admin@homazing.com.au" style="color:#8B7355;">admin@homazing.com.au</a> | +61 499 040 301</p>
</body>
</html>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Homazing Invoice - {address}"
    msg["From"]    = os.getenv("EMAIL_FROM", "Homazing <admin@homazing.com.au>")
    msg["To"]      = to_email
    msg["Cc"]      = ADMIN_EMAIL

    # Attach plain + HTML body
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(plain, "plain"))
    body_part.attach(MIMEText(html, "html"))
    msg.attach(body_part)

    # Generate and attach PDF
    if pricing:
        pdf_bytes = generate_invoice_pdf(
            invoice_number=invoice_number,
            contact_name=contact_name,
            address=address,
            pricing=pricing,
        )
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header(
            "Content-Disposition", "attachment",
            filename=f"Homazing-Invoice-{invoice_number}.pdf"
        )
        msg.attach(pdf_part)

    host     = os.getenv("EMAIL_HOST", "smtp.office365.com")
    port     = int(os.getenv("EMAIL_PORT", 587))
    user     = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(msg["From"], [to_email, ADMIN_EMAIL], msg.as_string())
