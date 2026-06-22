"""
Customer quote approval server.
GET  /approve/<token>  - decode base64 token, show styled quote + customer form
POST /approve/<token>  - create Zoho contact + invoice, return JSON result
"""

import base64
import json
import os
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Project Inclusions ────────────────────────────────────────────────────────

LIVING_SEQUENCE = [
    ("Living",  "Sofa (2&amp;3 seater / L-Shape / 3 Seater with occasional chair), rug, coffee table, entertainment unit, décor, cushions, artwork, floor lamp, greenery, console and mirror"),
    ("Family",  "Sofa (2&amp;3 seater / L-Shape / 3 Seater with occasional chair), coffee table, rug, décor, cushions, artwork, entertainment unit and greenery"),
    ("Rumpus",  "Sofa (2&amp;3 seater / L-Shape / 3 Seater with occasional chair), coffee table, rug, décor, cushions, artwork, entertainment unit and greenery"),
    ("Games",   "Sofa (2&amp;3 seater / L-Shape / 3 Seater with occasional chair), coffee table, rug, décor, cushions, artwork and greenery"),
]

GUEST_BEDROOM_ITEMS  = "Double bed, 2 bedside tables, 2 bedside lamps, artwork, bed linen, pillows and cushions"
KIDS_BEDROOM_ITEMS   = "Single bed, 1 bedside table, 1 bedside lamp, artwork, bed linen, pillows and cushions"

ROOM_INCLUSION_MAP = {
    "master_bedroom": ("Master Bedroom", "Double bed, bed head, 2 bedside tables, 2 bedside lamps, artwork, bed linen, rug, pillows, cushions and armchair*"),
    "kitchen":        ("Kitchen",        "Kitchen accessories for bench tops and bar stools"),
    "dining":         ("Dining",         "Dining set, accessories/décor pieces and artwork/greenery"),
    "bath":           ("Bathrooms",      "Towels, accessories and greenery"),
    "alfresco":       ("Alfresco",       "Outdoor lounge/table, chairs and accessories"),
    "study":          ("Study",          "Desk, chair, artwork and accessories"),
    "hallway_table":  ("Hallway",        "Artwork and accessories"),
    "small_living":   ("Living",         "Sofa, coffee table, rug, décor, cushions and artwork"),
}


def _build_inclusions(line_items: list, rooms: dict) -> list:
    inclusions = []
    source = rooms if rooms else {item["room"]: item["qty"] for item in line_items if "room" in item}
    if not source:
        return inclusions

    if source.get("master_bedroom", 0) >= 1:
        inclusions.append(ROOM_INCLUSION_MAP["master_bedroom"])

    # Shared bedroom counter starting at 2 — kids and guest share the same numbering
    bedroom_num = 2
    kids_qty = source.get("kids_bedroom", 0)
    for _ in range(kids_qty):
        inclusions.append((f"Bedroom {bedroom_num} (Kids)", KIDS_BEDROOM_ITEMS))
        bedroom_num += 1

    guest_qty = source.get("guest_bedroom", 0)
    for _ in range(guest_qty):
        inclusions.append((f"Bedroom {bedroom_num}", GUEST_BEDROOM_ITEMS))
        bedroom_num += 1

    living_qty = source.get("living", 0)
    for i in range(min(living_qty, len(LIVING_SEQUENCE))):
        inclusions.append(LIVING_SEQUENCE[i])

    if source.get("small_living", 0) >= 1:
        inclusions.append(ROOM_INCLUSION_MAP["small_living"])

    for key in ("kitchen", "dining", "bath", "alfresco", "study", "hallway_table"):
        if source.get(key, 0) >= 1:
            inclusions.append(ROOM_INCLUSION_MAP[key])

    return inclusions


def _inclusions_html(line_items: list, rooms: dict) -> str:
    inclusions = _build_inclusions(line_items, rooms)
    if not inclusions:
        return ""
    rows = "".join(
        f'<div class="inclusion-item"><p class="inclusion-name">{n}</p>'
        f'<p class="inclusion-detail">{d}</p></div>'
        for n, d in inclusions
    )
    return (
        '<div class="section">'
        '<p class="section-label">Project Inclusions</p>'
        f'<div class="inclusions-card">{rows}</div>'
        '</div>'
    )


# ── Token helpers ─────────────────────────────────────────────────────────────

def _decode_token(token: str) -> dict | None:
    try:
        padded = token + "=" * ((4 - len(token) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:
        return None


def _quote_table_rows(p: dict) -> str:
    return (
        f'<div class="line-item">'
        f'<div><p class="item-name">Hire / Setup / Transport</p>'
        f'<p class="item-desc">Full hire, setup and transport included</p></div>'
        f'<div class="item-price">${p["subtotal_ex_gst"]:,.0f}</div>'
        f'</div>'
    )



def _render_page(token: str, quote: dict) -> str:
    p = quote["pr"]
    rooms = quote.get("rm", {})
    address = quote.get("addr", "")
    expiry = (date.today() + timedelta(days=14)).strftime("%#d %B %Y")
    today_str = date.today().strftime("%#d %B %Y")
    rows = _quote_table_rows(p)
    inclusions_section = _inclusions_html(p.get("line_items", []), rooms)
    total_str = f"{p['total_inc_gst']:,.0f}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Property Styling Quote — Homazing</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;1,300;1,400&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --cream: #FAF8F4; --warm-white: #FFFFFF; --stone: #E8E3DA;
    --taupe: #B5AA98; --charcoal: #2C2825; --mid: #6B6259;
    --accent: #8B7355; --accent-light: #F0EAE0;
    --success: #3B6D11; --success-bg: #EAF3DE;
    --danger: #A32D2D; --danger-bg: #FCEBEB;
    --border: rgba(44,40,37,0.12); --border-med: rgba(44,40,37,0.2);
  }}
  body {{ font-family: 'DM Sans', sans-serif; background: var(--cream); color: var(--charcoal); min-height: 100vh; padding: 0 0 80px; }}

  /* Logo bar */
  .logo-bar {{ background: var(--warm-white); padding: 8px 40px; border-bottom: 1px solid var(--stone); }}
  .logo-bar img {{ height: 80px; display: block; }}

  /* Header */
  .header {{ background: var(--charcoal); padding: 48px 40px 40px; text-align: center; }}
  .header-eyebrow {{ font-size: 11px; font-weight: 500; letter-spacing: 0.2em; text-transform: uppercase; color: var(--taupe); margin-bottom: 12px; }}
  .header h1 {{ font-family: 'Cormorant Garamond', serif; font-size: 42px; font-weight: 300; color: #FAF8F4; letter-spacing: 0.02em; line-height: 1.2; }}
  .header h1 em {{ font-style: italic; font-weight: 300; }}
  .header-meta {{ margin-top: 24px; display: flex; justify-content: center; gap: 40px; flex-wrap: wrap; }}
  .header-meta-item {{ text-align: center; }}
  .header-meta-label {{ font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--taupe); margin-bottom: 4px; }}
  .header-meta-value {{ font-size: 14px; color: #FAF8F4; font-weight: 300; }}

  /* Status bar */
  .status-bar {{ background: var(--accent-light); border-bottom: 1px solid var(--stone); padding: 12px 40px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
  .status-badge {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }}
  .status-dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: pulse 2s ease-in-out infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.4}} }}
  .status-quote-num {{ font-size: 12px; font-weight: 500; letter-spacing: 0.08em; color: var(--mid); }}
  .status-expires {{ font-size: 12px; color: var(--mid); }}

  .container {{ max-width: 860px; margin: 0 auto; padding: 0 24px; }}
  .section {{ margin-top: 40px; }}
  .section-label {{ font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--taupe); margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid var(--stone); }}

  /* Project Inclusions */
  .inclusions-card {{ background: var(--warm-white); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  .inclusion-item {{ padding: 14px 24px; border-bottom: 1px solid var(--border); display: flex; gap: 20px; align-items: baseline; }}
  .inclusion-item:last-child {{ border-bottom: none; }}
  .inclusion-name {{ font-size: 14px; font-weight: 500; min-width: 180px; flex-shrink: 0; color: var(--charcoal); }}
  .inclusion-detail {{ font-size: 13px; color: var(--mid); line-height: 1.6; }}

  /* Quote table — 2 columns, no qty */
  .quote-table {{ background: var(--warm-white); border: 1px solid var(--border); border-radius: 12px 12px 0 0; overflow: hidden; }}
  .quote-table-header {{ display: grid; grid-template-columns: 1fr auto; padding: 12px 24px; background: var(--stone); gap: 16px; }}
  .quote-table-header span {{ font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--mid); font-weight: 400; }}
  .quote-table-header span:last-child {{ text-align: right; }}
  .line-item {{ display: grid; grid-template-columns: 1fr auto; padding: 16px 24px; gap: 16px; border-bottom: 1px solid var(--border); align-items: center; }}
  .line-item:last-child {{ border-bottom: none; }}
  .line-item:hover {{ background: var(--cream); }}
  .item-name {{ font-size: 15px; font-weight: 400; margin-bottom: 3px; }}
  .item-desc {{ font-size: 13px; color: var(--mid); }}
  .item-price {{ font-size: 15px; font-weight: 500; text-align: right; white-space: nowrap; min-width: 90px; }}

  /* Totals — flush below table */
  .totals {{ background: var(--warm-white); border: 1px solid var(--border); border-top: none; border-radius: 0 0 12px 12px; overflow: hidden; }}
  .total-row {{ display: flex; justify-content: space-between; padding: 13px 24px; border-bottom: 1px solid var(--border); font-size: 14px; }}
  .total-row:last-child {{ border-bottom: none; }}
  .total-row .label {{ color: var(--mid); }}
  .total-row.grand {{ background: var(--stone); padding: 18px 24px; }}
  .total-row.grand .label {{ font-family: 'Cormorant Garamond', serif; font-size: 18px; font-weight: 400; letter-spacing: 0.04em; color: var(--mid); }}
  .total-row.grand .amount {{ font-family: 'Cormorant Garamond', serif; font-size: 24px; font-weight: 400; color: var(--charcoal); }}

  /* Terms */
  .terms-box {{ background: var(--warm-white); border: 1px solid var(--border); border-radius: 12px; padding: 28px; }}
  .terms-section {{ padding: 10px 0; border-bottom: 1px solid var(--border); }}
  .terms-section:last-child {{ border-bottom: none; padding-bottom: 0; }}
  .terms-section:first-child {{ padding-top: 0; }}
  .terms-heading {{ font-size: 14px; font-weight: 500; color: var(--charcoal); margin-bottom: 4px; }}
  .terms-body {{ font-size: 13px; color: var(--mid); line-height: 1.6; }}

  /* Form */
  .form-card {{ background: var(--warm-white); border: 1px solid var(--border); border-radius: 12px; padding: 28px; }}
  .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .form-group {{ display: flex; flex-direction: column; gap: 6px; }}
  .form-group.full {{ grid-column: 1 / -1; }}
  .form-group label {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--mid); font-weight: 500; }}
  .form-group input {{ font-family: 'DM Sans', sans-serif; font-size: 14px; color: var(--charcoal); background: var(--cream); border: 1px solid var(--stone); border-radius: 8px; padding: 11px 14px; outline: none; transition: border-color 0.15s; }}
  .form-group input:focus {{ border-color: var(--accent); background: #fff; }}
  .form-group input::placeholder {{ color: var(--taupe); }}
  .form-group select {{ font-family: 'DM Sans', sans-serif; font-size: 14px; color: var(--charcoal); background: var(--cream); border: 1px solid var(--stone); border-radius: 8px; padding: 11px 14px; outline: none; cursor: pointer; transition: border-color 0.15s; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%236B6259' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 14px center; padding-right: 36px; }}
  .form-group select:focus {{ border-color: var(--accent); background-color: #fff; }}
  .contact-fields {{ transition: opacity 0.2s; }}
  .contact-fields.disabled {{ opacity: 0.38; pointer-events: none; }}
  .realtor-note {{ display: none; margin-top: 4px; padding: 12px 16px; background: var(--accent-light); border: 1px solid var(--stone); border-radius: 8px; font-size: 13px; color: var(--mid); line-height: 1.5; }}

  /* T&C checkbox */
  .tc-row {{ margin-top: 20px; display: flex; align-items: flex-start; gap: 10px; padding: 16px; background: var(--cream); border-radius: 8px; border: 1px solid var(--stone); }}
  .tc-row input[type="checkbox"] {{ margin-top: 2px; width: 16px; height: 16px; accent-color: var(--charcoal); flex-shrink: 0; cursor: pointer; }}
  .tc-row label {{ font-size: 13px; color: var(--mid); line-height: 1.5; cursor: pointer; }}
  .tc-row a {{ color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }}

  .action-section {{ margin-top: 20px; display: flex; gap: 12px; flex-wrap: wrap; }}
  .btn-approve {{ flex: 1; min-width: 200px; font-family: 'DM Sans', sans-serif; font-size: 14px; font-weight: 500; letter-spacing: 0.06em; padding: 16px 24px; background: var(--charcoal); color: #FAF8F4; border: none; border-radius: 10px; cursor: pointer; transition: background 0.15s, transform 0.1s, opacity 0.15s; }}
  .btn-approve:hover:not(:disabled) {{ background: #1a1714; transform: translateY(-1px); }}
  .btn-approve:disabled {{ opacity: 0.45; cursor: not-allowed; transform: none; }}
  .btn-decline {{ flex: 1; min-width: 160px; font-family: 'DM Sans', sans-serif; font-size: 14px; font-weight: 400; letter-spacing: 0.06em; padding: 16px 24px; background: transparent; color: var(--mid); border: 1px solid var(--stone); border-radius: 10px; cursor: pointer; transition: all 0.15s; }}
  .btn-decline:hover {{ border-color: var(--danger); color: var(--danger); background: var(--danger-bg); }}

  .error-msg {{ margin-top: 12px; font-size: 13px; color: var(--danger); display: none; }}

  /* Confirmations */
  .confirmation {{ display: none; text-align: center; padding: 48px 32px; background: var(--warm-white); border: 1px solid var(--border); border-radius: 12px; margin-top: 32px; }}
  .confirmation.approved {{ border-color: #3B6D11; background: var(--success-bg); }}
  .confirmation.declined {{ border-color: var(--danger); background: var(--danger-bg); }}
  .confirmation-icon {{ width: 52px; height: 52px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; font-size: 22px; }}
  .confirmation.approved .confirmation-icon {{ background: rgba(59,109,17,0.12); }}
  .confirmation.declined .confirmation-icon {{ background: rgba(163,45,45,0.1); }}
  .confirmation h3 {{ font-family: 'Cormorant Garamond', serif; font-size: 26px; font-weight: 400; margin-bottom: 8px; }}
  .confirmation.approved h3 {{ color: var(--success); }}
  .confirmation.declined h3 {{ color: var(--danger); }}
  .confirmation p {{ font-size: 14px; color: var(--mid); max-width: 400px; margin: 0 auto; line-height: 1.7; }}
  .invoice-ref {{ display: inline-block; margin-top: 16px; font-size: 13px; font-weight: 500; letter-spacing: 0.08em; color: var(--success); background: rgba(59,109,17,0.08); border-radius: 6px; padding: 10px 20px; line-height: 1.8; }}

  .footer {{ margin-top: 48px; text-align: center; padding: 24px; border-top: 1px solid var(--stone); }}
  .footer p {{ font-size: 12px; color: var(--taupe); }}

  @media (max-width: 600px) {{
    .header {{ padding: 36px 24px 32px; }}
    .header h1 {{ font-size: 32px; }}
    .header-meta {{ gap: 24px; }}
    .form-grid {{ grid-template-columns: 1fr; }}
    .form-group.full {{ grid-column: 1; }}
    .status-bar {{ padding: 12px 20px; }}
    .inclusion-item {{ flex-direction: column; gap: 4px; }}
    .inclusion-name {{ min-width: unset; }}
  }}
</style>
</head>
<body>

<div class="logo-bar">
  <img src="/logo" alt="Homazing" />
</div>

<div class="header">
  <p class="header-eyebrow">Property Styling Proposal</p>
  <h1><em>{address}</em></h1>
  <div class="header-meta">
    <div class="header-meta-item">
      <p class="header-meta-label">Date Issued</p>
      <p class="header-meta-value">{today_str}</p>
    </div>
    <div class="header-meta-item">
      <p class="header-meta-label">Agent</p>
      <p class="header-meta-value">{quote['ag']}</p>
    </div>
    <div class="header-meta-item">
      <p class="header-meta-label">Minimum Hire Period</p>
      <p class="header-meta-value">8 Weeks</p>
    </div>
    <div class="header-meta-item">
      <p class="header-meta-label">Install Date</p>
      <p class="header-meta-value">TBC</p>
    </div>
  </div>
</div>

<div class="status-bar">
  <span class="status-badge"><span class="status-dot"></span>Awaiting approval</span>
  <span class="status-quote-num">{quote['qn']}</span>
  <span class="status-expires">Quote valid until: {expiry}</span>
</div>

<div class="container">

  {inclusions_section}

  <div class="section">
    <p class="section-label">Quote</p>
    <div class="quote-table">
      <div class="quote-table-header">
        <span>Description</span>
        <span>Amount</span>
      </div>
      {rows}
    </div>
    <div class="totals">
      <div class="total-row">
        <span class="label">GST (10%)</span>
        <span>${p['gst']:,.0f}</span>
      </div>
      <div class="total-row grand">
        <span class="label">Total (inc. GST)</span>
        <span class="amount">${p['total_inc_gst']:,.0f}</span>
      </div>
    </div>
  </div>

  <div class="section">
    <p class="section-label">Extension Rates</p>
    <div class="quote-table">
      <div class="quote-table-header">
        <span>Description</span>
        <span>Amount</span>
      </div>
      <div class="line-item">
        <div><p class="item-name">Extension rate for further hire (weekly)</p><p class="item-desc">incl. GST</p></div>
        <div class="item-price">${round(p['total_inc_gst'] * 0.10):,}</div>
      </div>
    </div>
  </div>

  <div class="section">
    <p class="section-label">Terms &amp; Conditions</p>
    <div class="terms-box">
      <div class="terms-section">
        <p class="terms-heading">Minimum Hire Period</p>
        <p class="terms-body">A minimum hire term of eight (8) weeks applies, commencing from the confirmed installation date.</p>
      </div>
      <div class="terms-section">
        <p class="terms-heading">Extension of Hire</p>
        <p class="terms-body">Should you wish to extend the hire period, weekly extension rates will apply as outlined within this proposal.</p>
      </div>
      <div class="terms-section">
        <p class="terms-heading">Payment Terms</p>
        <p class="terms-body">An invoice will be issued upon formal acceptance of this quotation.<br>Full payment is required prior to installation. Payments can be made via direct deposit, bank transfer, or credit card.<br>Please ensure the property address is included as the payment reference. A remittance confirmation is to be provided once payment has been completed.</p>
      </div>
      <div class="terms-section">
        <p class="terms-heading">Installation</p>
        <p class="terms-body">Installation will be carried out on the scheduled date specified above, or the next available date where scheduling limitations apply (to be confirmed in advance).<br>The property must be clean and ready for styling, with all floors and surfaces cleared prior to arrival. A live electricity connection must be available at the property. If electricity is not connected, this must be disclosed prior to installation.</p>
      </div>
      <div class="terms-section">
        <p class="terms-heading">Collection / Removal</p>
        <p class="terms-body">Furniture will be collected at the conclusion of the hire period unless an extension has been arranged.<br>In the event the property is sold prior to the end of the agreed hire term, collection will be scheduled accordingly.<br>No credits or refunds will be provided for any unused portion of the hire period.</p>
      </div>
      <div class="terms-section">
        <p class="terms-heading">General Conditions</p>
        <p class="terms-body">All furniture and accessories are supplied strictly for display purposes and are not intended for regular use during the hire period.<br>Any damage, including that caused by pets, is not covered by insurance and will be assessed and charged to the client accordingly.</p>
      </div>
    </div>
  </div>

  <div class="section">
    <p class="section-label">Your Details &amp; Approval</p>
    <div class="form-card" id="approval-form">
      <div class="form-grid">
        <div class="form-group full">
          <label>I am a</label>
          <select id="client-type" onchange="updateFormType()">
            <option value="homeowner">Home Owner</option>
            <option value="realtor">Realtor / Agent</option>
          </select>
        </div>
      </div>

      <div class="realtor-note" id="realtor-note">
        &#10003;&nbsp; As the agent, your invoice will be sent directly to <strong>{quote.get('ae') or quote.get('ag', 'your agency email')}</strong>.
      </div>

      <div class="contact-fields" id="contact-fields" style="margin-top:16px;">
        <div class="form-grid">
          <div class="form-group">
            <label>Full Name *</label>
            <input type="text" id="client-name" placeholder="e.g. Sarah Johnson" />
          </div>
          <div class="form-group">
            <label>Email Address *</label>
            <input type="email" id="client-email" placeholder="e.g. sarah@email.com" />
          </div>
          <div class="form-group full">
            <label>Mobile Number *</label>
            <input type="tel" id="client-mobile" placeholder="e.g. 0412 345 678" />
          </div>
        </div>
      </div>

      <div class="tc-row" style="margin-top:20px;">
        <input type="checkbox" id="tc-checkbox" onchange="updateApproveBtn()" />
        <label for="tc-checkbox">
          I have read and agree to the
          <a href="/terms-pdf" target="_blank">Terms &amp; Conditions / Service Agreement</a>.
        </label>
      </div>

      <p class="error-msg" id="error-msg">Please enter your name, email and mobile number, and agree to the Terms &amp; Conditions.</p>

      <div class="action-section">
        <button class="btn-approve" id="btn-approve" onclick="submitApproval()" disabled>Approve &amp; Accept Quote</button>
        <button class="btn-decline" onclick="declineQuote()">Decline Quote</button>
      </div>
    </div>

    <div class="confirmation approved" id="confirm-approved">
      <div class="confirmation-icon">&#10003;</div>
      <h3>Quote Approved</h3>
      <p>Thank you! Your invoice has been created and will be sent to you shortly.</p>
      <p class="invoice-ref" id="invoice-ref"></p>
    </div>

    <div class="confirmation declined" id="confirm-declined">
      <div class="confirmation-icon">&#10005;</div>
      <h3>Quote Declined</h3>
      <p>No worries at all. We've noted your response. If you'd like to discuss adjustments or have any questions, please don't hesitate to reach out to Homazing.</p>
    </div>
  </div>

  <div class="footer">
    <p>Homazing Property Styling &middot; admin@homazing.com.au &middot; +61 499 040 301</p>
  </div>

</div>

<script>
  function updateFormType() {{
    const isRealtor = document.getElementById('client-type').value === 'realtor';
    const fields = document.getElementById('contact-fields');
    const note   = document.getElementById('realtor-note');
    fields.classList.toggle('disabled', isRealtor);
    note.style.display = isRealtor ? 'block' : 'none';
    if (isRealtor) {{
      ['client-name', 'client-email', 'client-mobile'].forEach(id => {{
        document.getElementById(id).value = '';
      }});
    }}
  }}

  function updateApproveBtn() {{
    document.getElementById('btn-approve').disabled = !document.getElementById('tc-checkbox').checked;
  }}

  async function submitApproval() {{
    const type     = document.getElementById('client-type').value;
    const isRealtor = type === 'realtor';
    const name     = document.getElementById('client-name').value.trim();
    const email    = document.getElementById('client-email').value.trim();
    const mobile   = document.getElementById('client-mobile').value.trim();
    const errEl    = document.getElementById('error-msg');

    if (!isRealtor && (!name || !email || !mobile)) {{
      errEl.textContent = 'Please enter your name, email and mobile number, and agree to the Terms & Conditions.';
      errEl.style.display = 'block';
      return;
    }}
    errEl.style.display = 'none';

    const btn = document.getElementById('btn-approve');
    btn.disabled = true;
    btn.textContent = 'Processing...';

    try {{
      const res  = await fetch(window.location.pathname, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{type, name, email, mobile}})
      }});
      const data = await res.json();

      if (res.ok) {{
        document.getElementById('approval-form').style.display = 'none';
        document.getElementById('invoice-ref').innerHTML =
          'Invoice ' + data.invoice_number + '<br>Total $' + {total_str} + ' (inc. GST)';
        document.getElementById('confirm-approved').style.display = 'block';
        document.getElementById('confirm-approved').scrollIntoView({{behavior: 'smooth', block: 'center'}});
      }} else {{
        errEl.textContent = data.error || 'Something went wrong. Please try again.';
        errEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Approve & Accept Quote';
      }}
    }} catch (e) {{
      errEl.textContent = 'Network error. Please try again.';
      errEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Approve & Accept Quote';
    }}
  }}

  function declineQuote() {{
    document.getElementById('approval-form').style.display = 'none';
    document.getElementById('confirm-declined').style.display = 'block';
    document.getElementById('confirm-declined').scrollIntoView({{behavior: 'smooth', block: 'center'}});
  }}
</script>
</body>
</html>"""
    return html


def _invalid_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invalid Link - Homazing</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  body { font-family: 'DM Sans', sans-serif; background: #FAF8F4; color: #2C2825; min-height: 100vh;
         display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 2rem; }
  h1 { font-family: 'Cormorant Garamond', serif; font-size: 36px; font-weight: 300; font-style: italic; margin-bottom: 1rem; }
  p { font-size: 14px; color: #6B6259; }
</style>
</head>
<body>
  <h1>Invalid link</h1>
  <p>This link is invalid or has expired. Please contact Homazing for a new quote link.</p>
</body>
</html>"""


@app.route("/approve/<token>", methods=["GET"])
def approval_form(token: str):
    quote = _decode_token(token)
    if not quote:
        return _invalid_page(), 400
    return _render_page(token, quote)


@app.route("/approve/<token>", methods=["POST"])
def approval_submit(token: str):
    quote = _decode_token(token)
    if not quote:
        return jsonify({"error": "Invalid or expired link."}), 400

    body         = request.get_json(silent=True) or {}
    contact_type = body.get("type", "homeowner")   # "homeowner" or "realtor"
    name         = body.get("name", "").strip()
    email        = body.get("email", "").strip()
    mobile       = body.get("mobile", "").strip()

    if contact_type != "realtor" and (not name or not email or not mobile):
        return jsonify({"error": "Name, email and mobile are required."}), 400

    try:
        from tools.zoho_create_contact     import create_contact
        from tools.zoho_create_invoice     import create_invoice
        from tools.zoho_send_invoice_email import send_invoice_email

        if contact_type == "realtor":
            # No contact created — invoice goes straight to the agency account
            agent_email = quote.get("ae", "")
            agent_name  = quote.get("ag", "Homazing Agent")
            invoice = create_invoice(
                contact_id = None,
                pricing    = quote["pr"],
                address    = quote.get("addr", ""),
                account_id = quote.get("aid", ""),
            )
            try:
                send_invoice_email(
                    to_email       = agent_email,
                    contact_name   = agent_name,
                    invoice_number = invoice["invoice_number"],
                    address        = quote.get("addr", ""),
                    total_inc_gst  = quote["pr"]["total_inc_gst"],
                    pricing        = quote["pr"],
                )
            except Exception as email_err:
                print(f"Invoice email (realtor) failed: {email_err}")
        else:
            # Home owner — create contact and send to them
            contact = create_contact(name, email, mobile, account_id=quote.get("aid", ""))
            invoice = create_invoice(
                contact_id = contact["id"],
                pricing    = quote["pr"],
                address    = quote.get("addr", ""),
                account_id = quote.get("aid", ""),
            )
            try:
                send_invoice_email(
                    to_email       = email,
                    contact_name   = name,
                    invoice_number = invoice["invoice_number"],
                    address        = quote.get("addr", ""),
                    total_inc_gst  = quote["pr"]["total_inc_gst"],
                    pricing        = quote["pr"],
                )
            except Exception as email_err:
                print(f"Invoice email (homeowner) failed: {email_err}")

        return jsonify({"invoice_number": invoice["invoice_number"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logo")
def serve_logo():
    logo_path = BASE_DIR / "tools" / "homazing-logo-cropped.png"
    return send_file(str(logo_path), mimetype="image/png")


@app.route("/terms-pdf")
def serve_terms_pdf():
    pdf_path = BASE_DIR / "Docs" / "Homazing Terms and Conditions Document.pdf"
    return send_file(str(pdf_path), mimetype="application/pdf")


if __name__ == "__main__":
    port = int(os.getenv("APPROVAL_PORT", 5000))
    print(f"Approval server running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
