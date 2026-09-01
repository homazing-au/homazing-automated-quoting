"""
Business logic behind the Telegram bot's staging/referral commands.

This is a copy of the same-named module in the Homazing_Sales_Agent project
(kept there as the source of truth for its own weekly sync job). It's
duplicated here - not imported cross-repo - because this bot deploys to
Render from this repo alone; a sibling-folder import would work locally but
break in production, where that other repo isn't checked out. If you change
the logic here, mirror the change in Homazing_Sales_Agent/tools/sheet_actions.py
(and vice versa) - they're expected to drift only in their credential loading
(this one reuses google_sheets.py's _get_credentials rather than its own).

Column layout (Staging Jobs tab): A=No. B=Address C=Suburb D=Agent E=Agent
Name F=Staged Date G=Advertised Date ... J=Staging Removed Date K=Auction/
Private Sale L=Auction/Sold Date M=Price Min N=Price Max O=Sold Price ...
X=Referral(Y/N) Y=Referral Amount Z=Referral Paid AA=Invoice No.
"""
import datetime

from googleapiclient.discovery import build

from tools.google_sheets import _get_credentials, _normalize_address

SHEET_ID = "1rSiOd_kTw2A8ynDnAcc9QvoUFQal3OidtcQ_RZRwu40"
TAB = "Staging Jobs"
EPOCH = datetime.date(1899, 12, 30)


def _service():
    return build("sheets", "v4", credentials=_get_credentials())


def _serial(d: datetime.date) -> int:
    return (d - EPOCH).days


def _today_serial() -> int:
    return _serial(datetime.date.today())


def _get_rows(range_end="AA200", render="UNFORMATTED_VALUE"):
    resp = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!A3:{range_end}",
        valueRenderOption=render,
    ).execute()
    rows = resp.get("values", [])
    return rows[1:]  # skip header row


def _cell(row, idx):
    return row[idx] if idx < len(row) else None


def _zoho_deal_id_by_addr() -> dict:
    """address (normalized) -> deal id, across every open/invoiced Zoho
    stage. Best-effort lookup used to attach a deal_id to a sheet-sourced
    candidate (for the Closed Won update, or an SMS contact lookup) -
    never used to filter which candidates show up."""
    from tools.zoho_list_invoiced_deals import list_invoiced_deals
    from tools.zoho_list_staging_candidates import list_staging_candidates

    by_addr = {}
    for d in list_invoiced_deals() + list_staging_candidates():
        if d.get("address"):
            by_addr.setdefault(_normalize_address(d["address"]), d["id"])
    return by_addr


def list_staging_complete_candidates() -> list[dict]:
    """Jobs that could still need staging: any Zoho deal not yet Closed Won/
    Closed Lost (awaiting approval, approved, or invoiced - staging can
    happen at any of those points), matched to its sheet row, excluding
    rows that already have a Staged Date (F)."""
    from tools.zoho_list_staging_candidates import list_staging_candidates

    zoho_deals = list_staging_candidates()
    sheet_rows = list(enumerate(_get_rows(), start=4))

    candidates = []
    for deal in zoho_deals:
        deal_addr = deal["address"]
        if not deal_addr:
            continue
        norm = _normalize_address(deal_addr)
        for i, row in sheet_rows:
            addr = _cell(row, 1)
            if addr and _normalize_address(addr) == norm:
                staged_date = _cell(row, 5)
                if not staged_date:
                    candidates.append({"row": i, "address": addr, "deal_id": deal["id"]})
                break
    return candidates


def mark_staged(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!F{row}",
        valueInputOption="RAW",
        body={"values": [[_today_serial()]]},
    ).execute()


def list_staging_removed_candidates() -> list[dict]:
    """Jobs with Staged Date (F) filled but Staging Removed Date (J) blank -
    currently staged, awaiting pickup. Sheet-only: an earlier version also
    required the matching Zoho deal to be in 'Invoiced' stage, but that
    silently hid older jobs whose deal had already moved past Invoiced (e.g.
    Closed Won) even though the staging itself hadn't been picked up yet.
    The sheet, not Zoho's stage, is the source of truth for what's
    physically staged."""
    zoho_by_addr = _zoho_deal_id_by_addr()
    candidates = []
    for i, row in enumerate(_get_rows(), start=4):
        addr = _cell(row, 1)
        staged_date = _cell(row, 5)
        removed_date = _cell(row, 9)
        if addr and staged_date and not removed_date:
            candidates.append({
                "row": i, "address": addr,
                "deal_id": zoho_by_addr.get(_normalize_address(addr), ""),
            })
    return candidates


def mark_staging_removed(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!J{row}",
        valueInputOption="RAW",
        body={"values": [[_today_serial()]]},
    ).execute()


def list_referral_candidates() -> list[dict]:
    """Jobs where a referral is owed (X=Y) and not yet paid (Z blank).
    Sheet-only, same reasoning as list_staging_removed_candidates - gating
    on Zoho's Invoiced stage hid older jobs whose deal had already moved
    past Invoiced. Looks up each row's matching Zoho deal (if any, from
    either the Invoiced or still-open stages) purely so mark_referral_paid
    can also flip that deal to Closed Won - a best-effort side effect, not
    a requirement for the job to show up here."""
    zoho_by_addr = _zoho_deal_id_by_addr()

    unformatted = _get_rows(render="UNFORMATTED_VALUE")
    formatted = _get_rows(render="FORMATTED_VALUE")
    candidates = []
    for i, (row, frow) in enumerate(zip(unformatted, formatted), start=4):
        addr = _cell(row, 1)
        referral_yn = _cell(row, 23)
        referral_paid = _cell(row, 25)
        if addr and referral_yn == "Y" and not referral_paid:
            amount_display = (_cell(frow, 24) or "$0").strip()
            deal_id = zoho_by_addr.get(_normalize_address(addr), "")
            candidates.append({
                "row": i, "address": addr,
                "amount_display": amount_display,
                "deal_id": deal_id,
            })
    return candidates


def mark_referral_paid(row: int, deal_id: str = "") -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!Z{row}",
        valueInputOption="RAW",
        body={"values": [["Y"]]},
    ).execute()
    if deal_id:
        from tools.zoho_update_quote import mark_deal_closed_won
        mark_deal_closed_won(deal_id)


def get_referral_amount_display(row: int) -> str:
    resp = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!Y{row}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    values = resp.get("values", [])
    return values[0][0].strip() if values and values[0] else "$0"
