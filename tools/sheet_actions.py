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

from tools.google_sheets import _get_credentials

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


def list_staging_complete_candidates() -> list[dict]:
    """Jobs with a blank Staged Date (F) - not yet marked as staged today."""
    candidates = []
    for i, row in enumerate(_get_rows(), start=4):
        addr = _cell(row, 1)
        staged_date = _cell(row, 5)
        if addr and not staged_date:
            candidates.append({"row": i, "address": addr})
    return candidates


def mark_staged(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!F{row}",
        valueInputOption="RAW",
        body={"values": [[_today_serial()]]},
    ).execute()


def list_staging_removed_candidates() -> list[dict]:
    """Jobs with Staged Date filled but Staging Removed Date (J) blank -
    currently staged, awaiting pickup."""
    candidates = []
    for i, row in enumerate(_get_rows(), start=4):
        addr = _cell(row, 1)
        staged_date = _cell(row, 5)
        removed_date = _cell(row, 9)
        if addr and staged_date and not removed_date:
            candidates.append({"row": i, "address": addr})
    return candidates


def mark_staging_removed(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!J{row}",
        valueInputOption="RAW",
        body={"values": [[_today_serial()]]},
    ).execute()


def list_referral_candidates() -> list[dict]:
    """Jobs where a referral is owed (X=Y) and not yet paid (Z blank)."""
    unformatted = _get_rows(render="UNFORMATTED_VALUE")
    formatted = _get_rows(render="FORMATTED_VALUE")
    candidates = []
    for i, (row, frow) in enumerate(zip(unformatted, formatted), start=4):
        addr = _cell(row, 1)
        referral_yn = _cell(row, 23)
        referral_paid = _cell(row, 25)
        if addr and referral_yn == "Y" and not referral_paid:
            amount_display = _cell(frow, 24) or "$0"
            candidates.append({"row": i, "address": addr, "amount_display": amount_display.strip()})
    return candidates


def mark_referral_paid(row: int) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!Z{row}",
        valueInputOption="RAW",
        body={"values": [["Y"]]},
    ).execute()


def get_referral_amount_display(row: int) -> str:
    resp = _service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"'{TAB}'!Y{row}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    values = resp.get("values", [])
    return values[0][0].strip() if values and values[0] else "$0"
