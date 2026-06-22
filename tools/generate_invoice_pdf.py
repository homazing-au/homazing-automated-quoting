"""Generate a Homazing Tax Invoice PDF matching the official invoice layout."""

import io
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image as PILImage, ImageDraw as PILDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, Image,
)
from reportlab.lib.enums import TA_RIGHT, TA_LEFT

# Load env
_base = Path(__file__).resolve().parent.parent
load_dotenv(_base.parent.parent / ".env")
load_dotenv(_base / ".env")

# Brand colours (from webpage CSS variables)
BLACK    = colors.HexColor("#1A1A1A")
DARK     = colors.HexColor("#333333")
MID      = colors.HexColor("#6B6259")   # --mid
TAUPE    = colors.HexColor("#B5AA98")   # --taupe  (header label text)
STONE    = colors.HexColor("#E8E3DA")   # --stone  (header strip bg)
RULE     = colors.HexColor("#CCCCCC")
WHITE    = colors.white

# Logo — dark-bg version (charcoal bg + gold logo); will be cropped to circle
LOGO_PATH = Path(
    r"C:\Users\manoj\OneDrive\5-Business\AI Agency\Clients\Homazing"
    r"\brand-assets\logos\dark-bg\homazing-master-dark-bg.png"
)


def _circular_logo_bytes(path: Path, size_px: int = 600) -> io.BytesIO | None:
    """Load logo, auto-trim dark border, resize to square, crop to circle."""
    if not path.exists():
        return None
    img = PILImage.open(path).convert("RGBA")

    # Auto-trim: find the bounding box of non-background pixels.
    # The dark-bg logo has a near-black background; the logo itself is brighter.
    # Convert to greyscale and threshold to find content.
    grey = img.convert("L")
    # Pixels brighter than threshold are "content"
    threshold = 40
    bbox = None
    pixels = grey.load()
    w, h = grey.size
    min_x, min_y, max_x, max_y = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            if pixels[x, y] > threshold:
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y

    if max_x > min_x and max_y > min_y:
        # Add 10% padding around content so the circle feels comfortable
        pad_x = int((max_x - min_x) * 0.10)
        pad_y = int((max_y - min_y) * 0.10)
        min_x = max(0, min_x - pad_x)
        min_y = max(0, min_y - pad_y)
        max_x = min(w, max_x + pad_x)
        max_y = min(h, max_y + pad_y)
        # Make square (use the larger dimension)
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        half = max((max_x - min_x), (max_y - min_y)) // 2
        min_x = max(0, cx - half)
        min_y = max(0, cy - half)
        max_x = min(w, cx + half)
        max_y = min(h, cy + half)
        img = img.crop((min_x, min_y, max_x, max_y))

    img = img.resize((size_px, size_px), PILImage.LANCZOS)

    # Circular mask
    mask = PILImage.new("L", (size_px, size_px), 0)
    draw = PILDraw.Draw(mask)
    draw.ellipse((0, 0, size_px - 1, size_px - 1), fill=255)

    result = PILImage.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    result.paste(img, mask=mask)

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _s(parent="Normal", **kw):
    base = getSampleStyleSheet()[parent]
    return ParagraphStyle("_" + str(hash(str(kw))), parent=base, **kw)


def generate_invoice_pdf(
    invoice_number: str,
    contact_name: str,
    address: str,
    pricing: dict,
) -> bytes:
    """Return one-page Tax Invoice PDF bytes matching the official Homazing layout."""

    issue_date = date.today().strftime("%d/%m/%Y")
    due_date   = (date.today() + timedelta(days=14)).strftime("%d/%m/%Y")
    subtotal   = pricing.get("subtotal_ex_gst", 0)
    gst        = pricing.get("gst", 0)
    total      = pricing.get("total_inc_gst", 0)

    # Company details from env
    legal_name    = os.getenv("COMPANY_LEGAL_NAME", "")
    trading_name  = os.getenv("COMPANY_TRADING_NAME", "Homazing")
    co_address    = os.getenv("COMPANY_ADDRESS", "")
    co_suburb     = os.getenv("COMPANY_SUBURB", "")
    co_phone      = os.getenv("COMPANY_PHONE", "")
    co_email      = os.getenv("COMPANY_EMAIL", "")
    co_website    = os.getenv("COMPANY_WEBSITE", "")
    co_abn        = os.getenv("COMPANY_ABN", "")
    bank_name     = os.getenv("BANK_ACCOUNT_NAME", "")
    bank_bsb      = os.getenv("BANK_BSB", "")
    bank_acct     = os.getenv("BANK_ACCOUNT", "")

    # ── Footer drawn directly on canvas so it anchors to page bottom ───────────
    def _draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TAUPE)
        page_w = A4[0]
        canvas.drawCentredString(page_w / 2, 10 * mm, legal_name)
        canvas.drawCentredString(page_w / 2,  6 * mm, "Page 1 of 1")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=14 * mm, bottomMargin=20 * mm,   # leave room for footer
    )

    story = []

    # ── TOP: Company info (left) + Logo (right) ────────────────────────────────
    co_block = [
        Paragraph(f"<b>{trading_name}</b>",
                  _s(fontSize=12, textColor=BLACK, leading=16)),
        Paragraph(co_address,  _s(fontSize=9, textColor=DARK, leading=13)),
        Paragraph(co_suburb,   _s(fontSize=9, textColor=DARK, leading=13)),
        Paragraph(co_phone,    _s(fontSize=9, textColor=DARK, leading=13)),
        Paragraph(co_email,    _s(fontSize=9, textColor=DARK, leading=13)),
        Paragraph(co_website,  _s(fontSize=9, textColor=DARK, leading=13)),
        Spacer(1, 2 * mm),
        Paragraph(f"ABN {co_abn}", _s(fontSize=9, textColor=DARK, leading=13)),
    ]

    # Circular logo — larger so text is legible inside the circle
    logo_cell = ""
    logo_buf = _circular_logo_bytes(LOGO_PATH, size_px=600)
    if logo_buf:
        logo_cell = Image(logo_buf, width=32 * mm, height=32 * mm)

    top_tbl = Table([[co_block, logo_cell]], colWidths=[113*mm, 61*mm])
    top_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ALIGN",         (1, 0), (1, 0),   "RIGHT"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (0, -1),  6),   # company info left edge → 6pt
        ("RIGHTPADDING",  (1, 0), (1, -1),  6),   # logo right edge → 6pt
    ]))
    story.append(top_tbl)
    story.append(Spacer(1, 6 * mm))

    # ── TAX INVOICE heading — in a table so it shares the 174mm grid ──────────
    ti_tbl = Table(
        [[Paragraph("Tax Invoice",
                    _s(fontSize=18, textColor=BLACK, fontName="Helvetica", leading=22))]],
        colWidths=[174 * mm],
    )
    ti_tbl.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),   # align with DATE
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(ti_tbl)
    story.append(Spacer(1, 5 * mm))

    # ── INVOICE TO (left) / Invoice meta (right) ───────────────────────────────
    lbl  = _s(fontSize=8,  textColor=TAUPE,  leading=11, fontName="Helvetica")
    val2 = _s(fontSize=9,  textColor=DARK,   leading=14, alignment=TA_RIGHT)
    lbl2 = _s(fontSize=8,  textColor=TAUPE,  leading=11, alignment=TA_RIGHT)

    bill_to = [
        Paragraph("INVOICE TO", lbl),
        Paragraph(contact_name, _s(fontSize=10, textColor=BLACK, leading=15)),
        Paragraph(address,      _s(fontSize=9,  textColor=DARK,  leading=14)),
    ]

    meta_right = Table([
        [Paragraph("INVOICE", lbl2),    Paragraph(invoice_number,   val2)],
        [Paragraph("DATE",    lbl2),    Paragraph(issue_date,        val2)],
        [Paragraph("TERMS",   lbl2),    Paragraph("Due on receipt",  val2)],
        [Paragraph("DUE DATE",lbl2),    Paragraph(due_date,          val2)],
    ], colWidths=[30*mm, 48*mm])
    meta_right.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (-1, 0), (-1, -1), 6),  # values right edge → align with AMOUNT
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))

    bill_tbl = Table([[bill_to, meta_right]], colWidths=[96*mm, 78*mm])
    bill_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (0, -1),  6),   # "INVOICE TO" left edge → align with DATE
    ]))
    story.append(bill_tbl)
    story.append(Spacer(1, 6 * mm))

    # ── Line items table ───────────────────────────────────────────────────────
    # 4 cols: DATE | DESCRIPTION | RATE | AMOUNT  (GST col removed)
    W = 174 * mm
    C = [25*mm, W - 25*mm - 26*mm - 26*mm, 26*mm, 26*mm]

    th   = _s(fontSize=8, textColor=MID, fontName="Helvetica",
               leading=11, spaceAfter=0)
    th_r = _s(fontSize=8, textColor=MID, fontName="Helvetica",
               alignment=TA_RIGHT, leading=11, spaceAfter=0)
    td   = _s(fontSize=9, textColor=DARK,  leading=14)
    td_r = _s(fontSize=9, textColor=DARK,  leading=14, alignment=TA_RIGHT)
    td_sm= _s(fontSize=8, textColor=MID,   leading=12)

    desc_cell = [
        Paragraph("Property Styling",
                  _s(fontSize=9, textColor=BLACK, fontName="Helvetica", leading=14)),
        Paragraph("As specified in the quote project inclusions", td_sm),
    ]

    header_row = [
        Paragraph("DATE",        th),
        Paragraph("DESCRIPTION", th),
        Paragraph("RATE",        th_r),
        Paragraph("AMOUNT",      th_r),
    ]
    item_row = [
        Paragraph(issue_date,          td),
        desc_cell,
        Paragraph(f"{subtotal:,.2f}",  td_r),
        Paragraph(f"{subtotal:,.2f}",  td_r),
    ]

    items_tbl = Table([header_row, item_row], colWidths=C)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  STONE),
        ("LINEBELOW",     (0, 1), (-1, 1),  0.5, RULE),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        # All rows: last col right edge 6pt → align with AMOUNT header

        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Totals ─────────────────────────────────────────────────────────────────
    # Labels right-aligned so they sit close to the amounts; values also right-aligned
    tot_lbl  = _s(fontSize=9, textColor=TAUPE, alignment=TA_RIGHT)
    tot_val  = _s(fontSize=9, textColor=DARK,  alignment=TA_RIGHT)
    bal_lbl  = _s(fontSize=9, textColor=MID,   alignment=TA_RIGHT, fontName="Helvetica-Bold")
    bal_val  = _s(fontSize=9, textColor=BLACK, alignment=TA_RIGHT, fontName="Helvetica-Bold")

    totals_tbl = Table([
        [Paragraph("GST 10%",     tot_lbl), Paragraph(f"{gst:,.2f}",     tot_val)],
        [Paragraph("BALANCE DUE", bal_lbl), Paragraph(f"A${total:,.2f}", bal_val)],
    ], colWidths=[174*mm - 52*mm, 52*mm])
    totals_tbl.setStyle(TableStyle([
        ("LINEABOVE",     (0, 1), (-1, 1), 0.5, RULE),
        ("LINEBELOW",     (0, 1), (-1, 1), 0.5, RULE),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),   # align right with AMOUNT
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 6 * mm))

    # ── Banking details — stone label strip, plain rows, no box ───────────────
    bk_hdr = _s(fontSize=8, textColor=MID, fontName="Helvetica",
                 leading=11, spaceAfter=0)
    bk_val = _s(fontSize=9, textColor=DARK,  leading=13)

    bank_rows = [
        [Paragraph("PAYMENT DETAILS", bk_hdr)],
        [Paragraph(f"Account Name:  {bank_name}", bk_val)],
        [Paragraph(f"BSB:  {bank_bsb}",           bk_val)],
        [Paragraph(f"Account:  {bank_acct}",       bk_val)],
    ]
    bank_tbl = Table(bank_rows, colWidths=[174*mm])
    bank_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  STONE),
        ("TOPPADDING",    (0, 0), (-1, 0),  4),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  4),
        ("TOPPADDING",    (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),   # breathing room inside strip
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(bank_tbl)

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()
